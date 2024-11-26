import asyncio
import json
import websockets
from datetime import datetime, timedelta
import sqlite3

# 存储在线用户的信息
online_users = {}
chat_history = []

# 存储用户最后发送消息的时间
last_message_time = {}

# 时间间隔限制，防止灌水
message_interval = timedelta(seconds=1)


async def register(websocket, path):
    username = None  # 初始化 username
    try:
        # 接收用户名
        await websocket.send(json.dumps({"type": "info", "message": "Enter your username:"}))
        #username = await websocket.recv()
        msg = await websocket.recv()
        msg = json.loads(msg)
        if 'message' in msg:
           username = msg['message']

        # 检查用户名是否唯一
        if username in online_users:
            await websocket.send(json.dumps({"type": "error", "message": "Username already taken."}))
            return

        # 注册用户
        session_id = id(websocket)
        online_users[username] = {"session_id": session_id, "login_time": datetime.now(), "websocket": websocket,
                                  "muted": False}

        # 通知用户成功登录
        await websocket.send(json.dumps({"type": "success", "message": f"Welcome {username}!"}))

        # 通知所有用户有新用户加入
        broadcast_message = json.dumps({"type": "info", "message": f"{username} has joined the chat."})
        await broadcast(broadcast_message)

        # 列出所有在线用户
        user_list = [{"username": user, "login_time": str(info["login_time"]), "session_id": info["session_id"]} for
                     user, info in online_users.items()]
        await websocket.send(json.dumps({"type": "user_list", "users": user_list}))

        # 主循环接收用户消息
        async for message in websocket:
            current_time = datetime.now()
            msg_data = json.loads(message)

            if "command" in msg_data:
                # 处理管理命令
                await handle_admin_command(msg_data["command"], username)
            elif not online_users[username]["muted"]:
                # 防止灌水：检查时间间隔
                if username in last_message_time and current_time - last_message_time[username] < message_interval:
                    await websocket.send(json.dumps({"type": "error", "message": "You are sending messages too fast."}))
                    continue

                # 更新最后发送消息的时间
                last_message_time[username] = current_time

                if "to" in msg_data:
                    # 处理私聊
                    target_user = msg_data["to"]
                    if target_user in online_users:
                        private_message = {"username": username, "message": msg_data["message"],
                                           "timestamp": str(current_time), "private": True}
                        await online_users[target_user]["websocket"].send(
                            json.dumps({"type": "chat", "data": private_message}))
                        await websocket.send(json.dumps({"type": "chat", "data": private_message}))  # 回显给自己
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "User not found."}))
                else:
                    # 公共消息
                    msg_data = {"username": username, "message": msg_data["message"], "timestamp": str(current_time)}
                    chat_history.append(msg_data)
                    print_chat_history()  # 打印并存储聊天记录
                    broadcast_message = json.dumps({"type": "chat", "data": msg_data})
                    await broadcast(broadcast_message)
            else:
                # 通知用户被禁言
                await websocket.send(
                    json.dumps({"type": "error", "message": "You are muted and cannot send messages."}))

    except websockets.ConnectionClosed:
        print(f"Connection with {username} closed.")
    finally:
        if username and username in online_users:
            del online_users[username]
            await broadcast(json.dumps({"type": "info", "message": f"{username} has left the chat."}))


async def handle_admin_command(command, username):
    parts = command.split()
    if len(parts) < 2:
        return

    action = parts[0]
    target_user = parts[1]

    if action == "mute" and target_user in online_users:
        online_users[target_user]["muted"] = True
        await broadcast(json.dumps({"type": "info", "message": f"{target_user} has been muted by {username}."}))
    elif action == "unmute" and target_user in online_users:
        online_users[target_user]["muted"] = False
        await broadcast(json.dumps({"type": "info", "message": f"{target_user} has been unmuted by {username}."}))
    elif action == "kick" and target_user in online_users:
        await online_users[target_user]["websocket"].close()
        del online_users[target_user]
        await broadcast(json.dumps({"type": "info", "message": f"{target_user} has been kicked out by {username}."}))


async def broadcast(message):
    """发送消息给所有在线用户"""
    await asyncio.gather(*(user["websocket"].send(message) for user in online_users.values()))


def init_db():
    """初始化数据库"""
    conn = sqlite3.connect('chat_history.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS chat_history
                      (timestamp TEXT, username TEXT, message TEXT)''')
    conn.commit()
    conn.close()


def store_chat_message(timestamp, username, message):
    """将聊天记录存储到数据库"""
    conn = sqlite3.connect('chat_history.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chat_history (timestamp, username, message) VALUES (?, ?, ?)',
                   (timestamp, username, message))
    conn.commit()
    conn.close()


def print_chat_history():
    """打印并存储聊天记录"""
    print("Chat History:")
    for msg in chat_history:
        timestamp = msg["timestamp"]
        username = msg["username"]
        message = msg["message"]
        print(f"[{timestamp}] {username}: {message}")
        store_chat_message(timestamp, username, message)


async def main():
    init_db()
    async with websockets.serve(register, "localhost", 8765):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    init_db()
    asyncio.run(main())
