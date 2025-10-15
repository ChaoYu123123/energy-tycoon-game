from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO

app = Flask(__name__)
app.secret_key = 'your_very_secret_key_here'
socketio = SocketIO(app)

# --- 全局遊戲狀態 ---
GAME_STATE = {}
available_roles = []
game_in_progress = False
total_player_count = 0
gm_sid = None  # 維持用來儲存關主的 session ID

# --- 網頁路由 (Routes) ---

@app.route('/')
def main_entry():
    return render_template('start.html', 
                           game_in_progress=game_in_progress, 
                           player_count=total_player_count)

@app.route('/roles')
def role_selection():
    if not game_in_progress:
        return redirect(url_for('main_entry'))
    return render_template('index.html', roles=available_roles)

# *** 修改點：移除了在這裡記錄 gm_sid 的邏輯 ***
@app.route('/select', methods=['POST'])
def select_role():
    selected_role = request.form.get('role')
    
    if selected_role in available_roles:
        available_roles.remove(selected_role)
        socketio.emit('role_taken', {'role': selected_role})
        # 直接跳轉，不再處理 sid
        return redirect(url_for('player_page', role_name=selected_role))
        
    return redirect(url_for('role_selection'))

@app.route('/player/<role_name>')
def player_page(role_name):
    if role_name in GAME_STATE:
        return render_template('player.html', role=role_name, data=GAME_STATE[role_name])
    else:
        return redirect(url_for('main_entry'))

# (gm_dashboard, update_player_data, end_game 函式維持不變)
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
    socketio.emit('game_over')
    return redirect(url_for('main_entry'))

# --- WebSocket 事件處理 ---

@socketio.on('connect')
def handle_connect():
    print(f'一位使用者已連線! SID: {request.sid}')

@socketio.on('setup_game')
def handle_setup_game(data):
    # (此函式維持不變)
    global game_in_progress, total_player_count, available_roles, GAME_STATE
    if not game_in_progress:
        player_count = int(data['player_count'])
        game_in_progress = True
        total_player_count = player_count
        
        player_names = [f"玩家{i}" for i in range(1, player_count)]
        player_names.append("關主")
        
        temp_game_state = {}
        for name in player_names:
            if name == "關主":
                temp_game_state[name] = {"money": 9999, "carbon": 999}
            else:
                temp_game_state[name] = {"money": 200, "carbon": 5}
        
        GAME_STATE = temp_game_state
        available_roles = list(GAME_STATE.keys())
        
        socketio.emit('game_is_ready', {'player_count': player_count})

# *** 新增：一個專門用來註冊玩家身份的事件 ***
@socketio.on('register_role')
def handle_register_role(data):
    global gm_sid
    role = data.get('role')
    if role == '關主':
        gm_sid = request.sid
        print(f"關主已註冊成功，Session ID: {gm_sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"一位使用者已斷線! SID: {request.sid}")
    if request.sid and request.sid == gm_sid:
        print("關主已斷線，正在重置遊戲...")
        reset_game_state()
        socketio.emit('game_over')

def reset_game_state():
    global GAME_STATE, available_roles, game_in_progress, total_player_count, gm_sid
    GAME_STATE = {}
    available_roles = []
    game_in_progress = False
    total_player_count = 0
    gm_sid = None
    print("所有遊戲狀態已重置。")