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

# --- 網頁路由 (Routes) ---

# 1. 遊戲入口
@app.route('/')
def main_entry():
    if game_in_progress:
        # 如果遊戲已開始，直接顯示大廳 (裡面有進入選角按鈕)
        return render_template('lobby.html', player_count=total_player_count)
    else:
        # 遊戲未開始，顯示設定畫面
        return render_template('start.html')

# (原本的 /setup_game 路由現在由 WebSocket 取代，可以刪除)

# 2. 角色選擇頁面
@app.route('/roles')
def role_selection():
    if not game_in_progress:
        return redirect(url_for('main_entry'))
    return render_template('index.html', roles=available_roles)

# (後續的路由 player_page, gm_dashboard 等維持不變)
@app.route('/select', methods=['POST'])
def select_role():
    selected_role = request.form.get('role')
    if selected_role in available_roles:
        available_roles.remove(selected_role)
        socketio.emit('role_taken', {'role': selected_role})
        print(f"角色 '{selected_role}' 已被選擇，已廣播更新。")
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
            socketio.emit('update_state', GAME_STATE)
        except ValueError:
            pass
    return redirect(url_for('gm_dashboard'))

@app.route('/end_game', methods=['POST'])
def end_game():
    global GAME_STATE, available_roles, game_in_progress, total_player_count
    GAME_STATE = {}
    available_roles = []
    game_in_progress = False
    total_player_count = 0
    socketio.emit('game_over')
    return redirect(url_for('main_entry'))


# --- WebSocket 事件處理 ---

@socketio.on('connect')
def handle_connect():
    print('一位使用者已連線！')

# **新功能：處理遊戲設定事件**
@socketio.on('setup_game')
def handle_setup_game(data):
    """當有玩家設定遊戲時觸發。"""
    global GAME_STATE, available_roles, game_in_progress, total_player_count
    
    # 確保遊戲只被設定一次
    if not game_in_progress:
        player_count = int(data['player_count'])
        
        game_in_progress = True
        total_player_count = player_count
        
        GAME_STATE = {}
        player_names = [f"玩家{i}" for i in range(1, player_count)]
        player_names.append("關主")
        
        for name in player_names:
            GAME_STATE[name] = {"money": 9999, "carbon": 999} if name == "關主" else {"money": 200, "carbon": 5}
        
        available_roles = list(GAME_STATE.keys())
        
        print(f"遊戲已設定！總人數: {player_count}, 角色: {available_roles}")
        
        # **重要：**
        # 向所有連接的客戶端廣播遊戲已準備就緒的事件
        socketio.emit('game_is_ready', {'player_count': player_count})

# --- 啟動伺服器 ---
#if __name__ == '__main__':
#    socketio.run(app, host='0.0.0.0', port=8000, debug=True)