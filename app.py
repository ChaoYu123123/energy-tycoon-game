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
gm_sid = None  # *** 新增：用來儲存關主的 session ID ***

# --- 網頁路由 (Routes) ---

# 1. 遊戲入口
@app.route('/')
def main_entry():
    # 無論遊戲是否開始，都渲染同一個 start.html 範本
    # 只是多傳送 game_in_progress 和 total_player_count 變數給前端
    return render_template('start.html', 
                           game_in_progress=game_in_progress, 
                           player_count=total_player_count)

# 2. 角色選擇頁面
@app.route('/roles')
def role_selection():
    if not game_in_progress:
        return redirect(url_for('main_entry'))
    return render_template('index.html', roles=available_roles)

# 3. 處理角色選擇的動作
@app.route('/select', methods=['POST'])
def select_role():
    global gm_sid # 宣告我們要修改全局變數
    selected_role = request.form.get('role')
    
    if selected_role in available_roles:
        available_roles.remove(selected_role)
        
        # *** 新增：如果選擇的是關主，就記錄他的 session ID ***
        if selected_role == '關主':
            gm_sid = request.sid
            print(f"關主已選擇角色，Session ID: {gm_sid}")

        socketio.emit('role_taken', {'role': selected_role})
        return redirect(url_for('player_page', role_name=selected_role))
        
    return redirect(url_for('role_selection'))

# 4. 玩家個人狀態頁面
@app.route('/player/<role_name>')
def player_page(role_name):
    if role_name in GAME_STATE:
        return render_template('player.html', role=role_name, data=GAME_STATE[role_name])
    else:
        return redirect(url_for('main_entry'))

# 5. 關主儀表板頁面
@app.route('/gm')
def gm_dashboard():
    if not game_in_progress:
        return redirect(url_for('main_entry'))
    return render_template('gm.html', game_state=GAME_STATE)

# 6. 處理關主更新玩家資源的動作
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
            pass # 如果輸入不是數字則忽略
            
    return redirect(url_for('gm_dashboard'))

# 7. 處理關主結束遊戲的動作
@app.route('/end_game', methods=['POST'])
def end_game():
    reset_game_state()
    socketio.emit('game_over') # 廣播遊戲結束事件
    return redirect(url_for('main_entry'))

# --- WebSocket 事件處理 ---

@socketio.on('connect')
def handle_connect():
    print('一位使用者已連線!')

# 新增：當有玩家設定遊戲時觸發
@socketio.on('setup_game')
def handle_setup_game(data):
    global game_in_progress, total_player_count, available_roles, GAME_STATE

    if not game_in_progress:
        player_count = int(data['player_count'])
        game_in_progress = True
        total_player_count = player_count
        
        # 建立角色
        player_names = [f"玩家{i}" for i in range(1, player_count)]
        player_names.append("關主")
        
        # 初始化遊戲狀態
        temp_game_state = {}
        for name in player_names:
            if name == "關主":
                temp_game_state[name] = {"money": 9999, "carbon": 999}
            else:
                temp_game_state[name] = {"money": 200, "carbon": 5}
        
        GAME_STATE = temp_game_state
        available_roles = list(GAME_STATE.keys())
        
        print(f"遊戲已設定! 總人數: {player_count}, 角色: {available_roles}")
        
        # 廣播遊戲已準備就緒
        socketio.emit('game_is_ready', {'player_count': player_count})

# *** 新增：處理使用者斷線事件 ***
@socketio.on('disconnect')
def handle_disconnect():
    print(f"一位使用者已斷線! Session ID: {request.sid}")
    # 檢查斷線的是不是關主
    if request.sid and request.sid == gm_sid:
        print("關主已斷線，正在重置遊戲...")
        reset_game_state()
        socketio.emit('game_over') # 廣播遊戲結束，讓所有還在線上的玩家被踢回首頁

# *** 新增：一個集中的遊戲重置函式 ***
def reset_game_state():
    """將所有全局遊戲狀態變數重置為初始值"""
    global GAME_STATE, available_roles, game_in_progress, total_player_count, gm_sid
    GAME_STATE = {}
    available_roles = []
    game_in_progress = False
    total_player_count = 0
    gm_sid = None # 重置關主 session ID
    print("所有遊戲狀態已重置。")

# (移除舊的 if __name__ == '__main__' 區塊，因為部署時不需要)