from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, join_room, leave_room, emit
import random

app = Flask(__name__)
app.secret_key = 'secret_key_for_session_management' # 請務必設定一個密鑰
socketio = SocketIO(app, manage_session=False) # 手動管理 Session 以避免衝突

# --- 多房間儲存區 ---
# 結構: { '房號': { 'game_state': {}, 'game_in_progress': False, 'host_sid': '...', ... } }
ROOMS = {}

# --- 輔助函式：取得當前使用者的房間 ---
def get_room():
    return session.get('room_code')

# --- 網頁路由 (Routes) ---

@app.route('/')
def main_entry():
    # 清除舊的 session，確保每次進首頁都是新的開始
    session.clear()
    return render_template('start.html')

@app.route('/roles')
def role_selection():
    room_code = get_room()
    if not room_code or room_code not in ROOMS:
        return redirect(url_for('main_entry'))
    
    room_data = ROOMS[room_code]
    if not room_data['game_in_progress']:
        return redirect(url_for('main_entry'))
        
    return render_template('index.html', roles=room_data['available_roles'])

@app.route('/select', methods=['POST'])
def select_role():
    room_code = get_room()
    selected_role = request.form.get('role')
    
    if room_code in ROOMS:
        room_data = ROOMS[room_code]
        if selected_role in room_data['available_roles']:
            room_data['available_roles'].remove(selected_role)
            # 只對該房間廣播
            socketio.emit('role_taken', {'role': selected_role}, room=room_code)
            return redirect(url_for('player_page', role_name=selected_role))
            
    return redirect(url_for('role_selection'))

@app.route('/player/<role_name>')
def player_page(role_name):
    room_code = get_room()
    if room_code in ROOMS:
        game_state = ROOMS[room_code]['game_state']
        if role_name in game_state:
            return render_template('player.html', role=role_name, data=game_state[role_name])
    
    return redirect(url_for('main_entry'))

@app.route('/gm')
def gm_dashboard():
    room_code = get_room()
    if room_code in ROOMS and ROOMS[room_code]['game_in_progress']:
        return render_template('gm.html', game_state=ROOMS[room_code]['game_state'])
    return redirect(url_for('main_entry'))

@app.route('/gm/update', methods=['POST'])
def update_player_data():
    room_code = get_room()
    player_to_update = request.form.get('player_name')
    resource_type = request.form.get('resource_type')
    amount_str = request.form.get('amount')

    if room_code in ROOMS:
        game_state = ROOMS[room_code]['game_state']
        if player_to_update in game_state and resource_type in ['money', 'carbon'] and amount_str:
            try:
                amount = int(amount_str)
                game_state[player_to_update][resource_type] += amount
                game_state['關主'][resource_type] -= amount
                socketio.emit('update_state', game_state, room=room_code)
            except ValueError:
                pass
            
    return redirect(url_for('gm_dashboard'))

@app.route('/end_game', methods=['POST'])
def end_game():
    room_code = get_room()
    if room_code in ROOMS:
        # 1. 廣播結束事件給房間內所有人 (這會觸發前端跳轉)
        socketio.emit('game_over', room=room_code)
        
        # 2. 刪除房間數據
        del ROOMS[room_code]
        print(f"房間 {room_code} 已關閉")
        
    # 3. 關主自己跳轉回首頁
    return redirect(url_for('main_entry'))

# --- WebSocket 事件處理 ---

@socketio.on('connect')
def handle_connect():
    print(f'使用者連線: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    # 尋找該 SID 在哪個房間
    for code, data in ROOMS.items():
        if request.sid in data['connected_sids']:
            data['connected_sids'].remove(request.sid)
            # 更新該房間的人數
            socketio.emit('update_player_list', {'count': len(data['connected_sids'])}, room=code)
            break

@socketio.on('create_room')
def handle_create_room():
    # 生成不重複房號
    while True:
        new_code = str(random.randint(100000, 999999))
        if new_code not in ROOMS:
            break
            
    # 初始化房間數據
    ROOMS[new_code] = {
        'host_sid': request.sid,
        'connected_sids': [request.sid],
        'game_in_progress': False,
        'game_state': {},
        'available_roles': []
    }
    
    # 將 Socket 加入房間頻道
    join_room(new_code)
    # 儲存房號到 Session (重要！)
    session['room_code'] = new_code
    
    print(f"房間 {new_code} 已建立")
    emit('room_created', {'code': new_code, 'is_host': True})
    emit('update_player_list', {'count': 1}, room=new_code)

@socketio.on('join_game_room')
def handle_join_room(data):
    code = data.get('code')
    
    if code in ROOMS:
        if ROOMS[code]['game_in_progress']:
             emit('error_message', {'msg': '該房間遊戲已開始，無法加入'})
             return

        join_room(code)
        session['room_code'] = code
        ROOMS[code]['connected_sids'].append(request.sid)
        
        print(f"玩家加入房間 {code}")
        emit('room_joined', {'is_host': False})
        emit('update_player_list', {'count': len(ROOMS[code]['connected_sids'])}, room=code)
    else:
        emit('error_message', {'msg': '找不到此房間號碼'})

@socketio.on('start_game')
def handle_start_game():
    room_code = get_room() # 從 session 拿房號
    
    if not room_code or room_code not in ROOMS:
        return
        
    room_data = ROOMS[room_code]
    
    # 權限檢查
    if request.sid != room_data['host_sid']:
        return

    current_count = len(room_data['connected_sids'])
    
    if current_count < 2:
        emit('error_message', {'msg': '人數不足，至少需要 2 人才能開始！'})
        return

    if not room_data['game_in_progress']:
        room_data['game_in_progress'] = True
        
        # 建立角色
        player_names = [f"玩家{i}" for i in range(1, current_count)]
        player_names.append("關主")
        
        temp_game_state = {}
        for name in player_names:
            if name == "關主":
                temp_game_state[name] = {"money": 9999, "carbon": 999}
            else:
                temp_game_state[name] = {"money": 200, "carbon": 5}
        
        room_data['game_state'] = temp_game_state
        room_data['available_roles'] = list(temp_game_state.keys())
        
        print(f"房間 {room_code} 遊戲開始! 人數: {current_count}")
        
        # 只通知該房間的人跳轉
        socketio.emit('game_started_redirect', room=room_code)

# 讓玩家重新連上 socket 時重新加入房間 (解決頁面跳轉後 socket 斷開問題)
@socketio.on('rejoin_room_request')
def handle_rejoin():
    room_code = get_room()
    if room_code and room_code in ROOMS:
        join_room(room_code)
        print(f"SID {request.sid} 重新連線至房間 {room_code}")

# 註冊角色身分 (用於背景圖判斷等)
@socketio.on('register_role')
def handle_register_role(data):
    # 這裡可以依需求擴充
    pass