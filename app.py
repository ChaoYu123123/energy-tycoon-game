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
ROOM_CODE = None        # 儲存當前的 6 位數房號
HOST_SID = None         # 記錄房主 (第一位玩家) 的 Session ID
CONNECTED_PLAYERS = []  # 儲存所有在等待室的玩家 SID

# --- 網頁路由 (Routes) ---

@app.route('/')
def main_entry():
    # 根據是否已有房間，決定前端顯示什麼模式
    room_status = 'active' if ROOM_CODE else 'empty'
    
    # 如果遊戲已經開始，且不是新加入的人，顯示遊戲進行中畫面 (這裡簡化處理)
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
        socketio.emit('role_taken', {'role': selected_role})
        return redirect(url_for('player_page', role_name=selected_role))
    return redirect(url_for('role_selection'))

@app.route('/player/<role_name>')
def player_page(role_name):
    if role_name in GAME_STATE:
        return render_template('player.html', role=role_name, data=GAME_STATE[role_name])
    else:
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
            with app.app_context():
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

# --- WebSocket 事件處理 (大改版) ---

@socketio.on('connect')
def handle_connect():
    print(f'新連線建立: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    global CONNECTED_PLAYERS
    print(f"使用者斷線: {request.sid}")
    
    # 從玩家列表中移除
    if request.sid in CONNECTED_PLAYERS:
        CONNECTED_PLAYERS.remove(request.sid)
        # 更新等待室人數
        socketio.emit('update_player_list', {'count': len(CONNECTED_PLAYERS)})

    # 如果斷線的是房主，且遊戲還沒開始，則重置房間
    if request.sid == HOST_SID:
        print("房主已斷線，重置所有狀態...")
        reset_game_state()
        socketio.emit('host_disconnected') # 通知所有人房主跑了

# 1. 建立房間 (房主專用)
@socketio.on('create_room')
def handle_create_room():
    global ROOM_CODE, HOST_SID, CONNECTED_PLAYERS
    
    if ROOM_CODE is None:
        # 生成 6 位數隨機碼
        ROOM_CODE = str(random.randint(100000, 999999))
        HOST_SID = request.sid
        CONNECTED_PLAYERS.append(request.sid)
        
        print(f"房間已建立! 代碼: {ROOM_CODE}, 房主: {HOST_SID}")
        # 回傳成功訊息給房主
        socketio.emit('room_created', {'code': ROOM_CODE, 'is_host': True}, to=request.sid)
        # 更新人數
        socketio.emit('update_player_list', {'count': len(CONNECTED_PLAYERS)})

# 2. 加入房間 (其他玩家用)
@socketio.on('join_game_room')
def handle_join_room(data):
    global CONNECTED_PLAYERS
    input_code = data.get('code')
    
    if ROOM_CODE and input_code == ROOM_CODE:
        CONNECTED_PLAYERS.append(request.sid)
        print(f"玩家 {request.sid} 加入了房間")
        # 回傳加入成功
        socketio.emit('room_joined', {'is_host': False}, to=request.sid)
        # 廣播更新人數給所有人
        socketio.emit('update_player_list', {'count': len(CONNECTED_PLAYERS)})
    else:
        # 驗證失敗
        socketio.emit('error_message', {'msg': '房間號碼錯誤或房間不存在'}, to=request.sid)

# 3. 開始遊戲 (房主觸發)
@socketio.on('start_game')
def handle_start_game():
    global game_in_progress, total_player_count, available_roles, GAME_STATE
    
    # 只有房主能開始
    if request.sid != HOST_SID:
        return

    # 自動計算人數
    current_count = len(CONNECTED_PLAYERS)
    
    if current_count < 3: # 至少要有 3 人 (例如 2 玩家 + 1 關主)
        socketio.emit('error_message', {'msg': '人數不足，至少需要 3 人才能開始！'}, to=request.sid)
        return

    if not game_in_progress:
        game_in_progress = True
        total_player_count = current_count
        
        # 動態建立角色 (總人數 - 1 個玩家, 1 個關主)
        player_names = [f"玩家{i}" for i in range(1, current_count)]
        player_names.append("關主")
        
        temp_game_state = {}
        for name in player_names:
            if name == "關主":
                temp_game_state[name] = {"money": 9999, "carbon": 999}
            else:
                temp_game_state[name] = {"money": 200, "carbon": 5}
        
        GAME_STATE = temp_game_state
        available_roles = list(GAME_STATE.keys())
        
        print(f"遊戲開始! 人數: {current_count}, 角色: {available_roles}")
        
        with app.app_context():
            # 廣播跳轉訊號，讓所有人進入選角頁面
            socketio.emit('game_started_redirect')

# 4. 玩家註冊 (維持不變)
@socketio.on('register_role')
def handle_register_role(data):
    # 這裡可以保留邏輯，如果需要的話
    pass

def reset_game_state():
    global GAME_STATE, available_roles, game_in_progress, total_player_count, ROOM_CODE, HOST_SID, CONNECTED_PLAYERS
    GAME_STATE = {}
    available_roles = []
    game_in_progress = False
    total_player_count = 0
    ROOM_CODE = None
    HOST_SID = None
    CONNECTED_PLAYERS = []
    print("所有遊戲狀態已重置。")