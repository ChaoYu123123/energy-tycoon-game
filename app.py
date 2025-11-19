from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, join_room, leave_room
import random

app = Flask(__name__)
app.secret_key = 'your_very_secret_key_here'
socketio = SocketIO(app)

# --- 全局遊戲狀態 ---
GAME_STATE = {}
available_roles = []
game_in_progress = False
total_player_count = 0

# 房間系統變數
ROOM_CODE = None
HOST_SID = None
CONNECTED_PLAYERS = []

# --- 網頁路由 (Routes) ---

@app.route('/')
def main_entry():
    room_status = 'active' if ROOM_CODE else 'empty'
    if game_in_progress:
        return render_template('start.html', view_mode='game_running')
    return render_template('start.html', view_mode=room_status)

@app.route('/roles')
def role_selection():
    if not game_in_progress:
        return redirect(url_for('main_entry'))
    return render_template('index.html', roles=available_roles)

@app.route('/select', methods=['POST'])
def select_role():
    selected_role = request.form.get('role')
    if selected_role in available_roles:
        available_roles.remove(selected_role)
        # 廣播角色被選走 (不需要 app_context，因為這是 HTTP 請求)
        socketio.emit('role_taken', {'role': selected_role})
        return redirect(url_for('player_page', role_name=selected_role))
    return redirect(url_for('role_selection'))

@app.route('/player/<role_name>')
def player_page(role_name):
    if role_name in GAME_STATE:
        return render_template('player.html', role=role_name, data=GAME_STATE[role_name])
    else:
        # 如果玩家狀態不見了，回到首頁
        return redirect(url_for('main_entry'))

@app.route('/gm')
def gm_dashboard():
    if not game_in_progress:
        return redirect(url_for('main_entry'))
    return render_template('gm.html', game_state=GAME_STATE)

@app.route('/gm/update', methods=['POST'])
def update_player_data():
    player_to_update = request.form.get('player_name')
    resource_type = request.form.get('resource_type')
    amount_str = request.form.get('amount')

    if player_to_update in GAME_STATE and resource_type in ['money', 'carbon'] and amount_str:
        try:
            amount = int(amount_str)
            GAME_STATE[player_to_update][resource_type] += amount
            GAME_STATE['關主'][resource_type] -= amount
            socketio.emit('update_state', GAME_STATE)
        except ValueError:
            pass
    return redirect(url_for('gm_dashboard'))

@app.route('/end_game', methods=['POST'])
def end_game():
    reset_game_state()
    with app.app_context():
        socketio.emit('game_over')
    return redirect(url_for('main_entry'))

# --- WebSocket 事件處理 ---

@socketio.on('connect')
def handle_connect():
    print(f'新連線建立: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    global CONNECTED_PLAYERS
    print(f"使用者斷線: {request.sid}")
    
    if request.sid in CONNECTED_PLAYERS:
        CONNECTED_PLAYERS.remove(request.sid)
        socketio.emit('update_player_list', {'count': len(CONNECTED_PLAYERS)})

    # *** 重要修正：移除「房主斷線自動重置」的邏輯 ***
    # 因為當房主跳轉頁面（例如從等待室->選角->個人頁面）時，
    # 瀏覽器會觸發 disconnect，導致遊戲被錯誤重置。
    # 我們改由「結束遊戲」按鈕來手動重置，這樣比較穩定。
    # if request.sid == HOST_SID:
    #     print("房主已斷線...") 

@socketio.on('create_room')
def handle_create_room():
    global ROOM_CODE, HOST_SID, CONNECTED_PLAYERS
    
    if ROOM_CODE is None:
        ROOM_CODE = str(random.randint(100000, 999999))
        HOST_SID = request.sid
        CONNECTED_PLAYERS.append(request.sid)
        
        print(f"房間已建立! 代碼: {ROOM_CODE}, 房主: {HOST_SID}")
        socketio.emit('room_created', {'code': ROOM_CODE, 'is_host': True}, to=request.sid)
        socketio.emit('update_player_list', {'count': len(CONNECTED_PLAYERS)})

@socketio.on('join_game_room')
def handle_join_room(data):
    global CONNECTED_PLAYERS
    input_code = data.get('code')
    
    if ROOM_CODE and input_code == ROOM_CODE:
        CONNECTED_PLAYERS.append(request.sid)
        print(f"玩家 {request.sid} 加入了房間")
        socketio.emit('room_joined', {'is_host': False}, to=request.sid)
        socketio.emit('update_player_list', {'count': len(CONNECTED_PLAYERS)})
    else:
        socketio.emit('error_message', {'msg': '房間號碼錯誤或房間不存在'}, to=request.sid)

@socketio.on('start_game')
def handle_start_game():
    global game_in_progress, total_player_count, available_roles, GAME_STATE
    
    if request.sid != HOST_SID:
        return

    current_count = len(CONNECTED_PLAYERS)