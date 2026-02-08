#!/usr/bin/env python3

import json
import threading
import os
import socket
import hashlib
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

from room import get_all_rooms, get_room_detail, admin_force_destroy_room, admin_force_kick_player, admin_force_ready

# 获取当前文件的绝对路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

ADMIN_PORT = 8083

# 管理员凭证
ADMIN_USERNAME = "管理员用户名"
ADMIN_PASSWORD = "管理面板密码"

# 会话管理
sessions = {}
SESSION_TIMEOUT = 3600  # 1小时

# 操作日志文件
ADMIN_LOG_FILE = "admin_operations.log"

# 操作频率限制
operation_limits = defaultdict(list)
MAX_OPERATIONS_PER_MINUTE = 10

# 跨服务器管理器
inter_server_manager = None

def set_inter_server_manager(manager):
    """设置跨服务器管理器"""
    global inter_server_manager
    inter_server_manager = manager

def hash_password(password):
    """使用SHA256哈希密码"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def generate_session_token():
    """生成会话令牌"""
    import secrets
    return secrets.token_hex(32)

def is_session_valid(token):
    """检查会话是否有效"""
    if token not in sessions:
        return False
    
    session_time = sessions[token]
    current_time = time.time()
    
    if current_time - session_time > SESSION_TIMEOUT:
        del sessions[token]
        return False
    
    return True

def check_rate_limit(ip_address):
    """检查操作频率限制"""
    current_time = time.time()
    
    # 清理超过1分钟的记录
    operation_limits[ip_address] = [
        t for t in operation_limits[ip_address] 
        if current_time - t < 60
    ]
    
    if len(operation_limits[ip_address]) >= MAX_OPERATIONS_PER_MINUTE:
        return False
    
    operation_limits[ip_address].append(current_time)
    return True

def log_operation(operation_type, details, admin_ip):
    """记录管理员操作日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] [{admin_ip}] {operation_type}: {details}\n"
    
    try:
        with open(ADMIN_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Failed to write admin log: {e}")

def get_client_ip(client_socket):
    """获取客户端IP地址"""
    try:
        return client_socket.getpeername()[0]
    except:
        return "unknown"

def send_json_response(client_socket, data, status_code=200):
    """发送JSON响应"""
    response_body = json.dumps(data, ensure_ascii=False)
    response = f'HTTP/1.1 {status_code} OK\r\n'
    response += f'Content-Type: application/json\r\n'
    response += f'Access-Control-Allow-Origin: *\r\n'
    response += f'Content-Length: {len(response_body.encode("utf-8"))}\r\n'
    response += '\r\n'
    response += response_body
    client_socket.sendall(response.encode('utf-8'))

def send_html_response(client_socket, html_content):
    """发送HTML响应"""
    response = f'HTTP/1.1 200 OK\r\n'
    response += f'Content-Type: text/html; charset=utf-8\r\n'
    response += f'Content-Length: {len(html_content.encode("utf-8"))}\r\n'
    response += '\r\n'
    response += html_content
    client_socket.sendall(response.encode('utf-8'))

def send_error_response(client_socket, message, status_code=400):
    """发送错误响应"""
    response_body = json.dumps({"status": "error", "message": message}, ensure_ascii=False)
    response = f'HTTP/1.1 {status_code} Error\r\n'
    response += f'Content-Type: application/json\r\n'
    response += f'Access-Control-Allow-Origin: *\r\n'
    response += f'Content-Length: {len(response_body.encode("utf-8"))}\r\n'
    response += '\r\n'
    response += response_body
    client_socket.sendall(response.encode('utf-8'))

def handle_login(request_data, client_socket, client_ip):
    """处理登录请求"""
    try:
        content_length = 0
        for line in request_data.split('\r\n'):
            if line.startswith('Content-Length:'):
                content_length = int(line.split(':')[1].strip())
                break
        
        if content_length > 0:
            body = request_data.split('\r\n\r\n')[1]
            while len(body) < content_length:
                body += client_socket.recv(1024).decode('utf-8')
            
            login_data = json.loads(body)
            username = login_data.get('username')
            password = login_data.get('password')
            
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                token = generate_session_token()
                sessions[token] = time.time()
                log_operation("LOGIN", f"管理员登录成功", client_ip)
                send_json_response(client_socket, {"status": "success", "token": token})
            else:
                log_operation("LOGIN_FAILED", f"登录失败: 用户名或密码错误", client_ip)
                send_error_response(client_socket, "用户名或密码错误", 401)
        else:
            send_error_response(client_socket, "缺少请求体", 400)
    except Exception as e:
        log_operation("LOGIN_ERROR", f"登录处理错误: {str(e)}", client_ip)
        send_error_response(client_socket, "登录处理失败", 500)

def handle_get_rooms(client_socket, client_ip):
    """处理获取房间列表请求"""
    if not check_rate_limit(client_ip):
        send_error_response(client_socket, "操作过于频繁，请稍后再试", 429)
        return
    
    global inter_server_manager
    if inter_server_manager:
        result = {
            "status": "0",
            "rooms": inter_server_manager.get_all_rooms_from_all_servers()
        }
    else:
        result = get_all_rooms()
    send_json_response(client_socket, result)

def handle_get_room_detail(room_id, client_socket, client_ip):
    """处理获取房间详情请求"""
    if not check_rate_limit(client_ip):
        send_error_response(client_socket, "操作过于频繁，请稍后再试", 429)
        return
    
    global inter_server_manager
    if inter_server_manager:
        result = inter_server_manager.get_room_detail_from_all_servers(room_id)
    else:
        result = get_room_detail(room_id)
    send_json_response(client_socket, result)

def handle_destroy_room(request_data, client_socket, client_ip, token):
    """处理解散房间请求"""
    if not check_rate_limit(client_ip):
        send_error_response(client_socket, "操作过于频繁，请稍后再试", 429)
        return
    
    try:
        content_length = 0
        for line in request_data.split('\r\n'):
            if line.startswith('Content-Length:'):
                content_length = int(line.split(':')[1].strip())
                break
        
        if content_length > 0:
            body = request_data.split('\r\n\r\n')[1]
            while len(body) < content_length:
                body += client_socket.recv(1024).decode('utf-8')
            
            data = json.loads(body)
            room_id = data.get('roomId')
            confirmed = data.get('confirmed', False)
            
            if not confirmed:
                send_error_response(client_socket, "请确认操作", 400)
                return
            
            result = admin_force_destroy_room(room_id)
            
            if result["status"] == "0":
                log_operation("DESTROY_ROOM", f"解散房间: {room_id}", client_ip)
                send_json_response(client_socket, {"status": "success", "message": "房间已解散"})
            else:
                send_error_response(client_socket, "房间不存在", 404)
    except Exception as e:
        log_operation("DESTROY_ROOM_ERROR", f"解散房间错误: {str(e)}", client_ip)
        send_error_response(client_socket, "解散房间失败", 500)

def handle_kick_player(request_data, client_socket, client_ip, token):
    """处理踢出玩家请求"""
    if not check_rate_limit(client_ip):
        send_error_response(client_socket, "操作过于频繁，请稍后再试", 429)
        return
    
    try:
        content_length = 0
        for line in request_data.split('\r\n'):
            if line.startswith('Content-Length:'):
                content_length = int(line.split(':')[1].strip())
                break
        
        if content_length > 0:
            body = request_data.split('\r\n\r\n')[1]
            while len(body) < content_length:
                body += client_socket.recv(1024).decode('utf-8')
            
            data = json.loads(body)
            room_id = data.get('roomId')
            user_id = data.get('userId')
            confirmed = data.get('confirmed', False)
            
            if not confirmed:
                send_error_response(client_socket, "请确认操作", 400)
                return
            
            result = admin_force_kick_player(room_id, user_id)
            
            if result["status"] == "0":
                log_operation("KICK_PLAYER", f"踢出玩家: {user_id} from {room_id}", client_ip)
                send_json_response(client_socket, {"status": "success", "message": "玩家已踢出"})
            elif result["status"] == "1":
                send_error_response(client_socket, "房间不存在", 404)
            else:
                send_error_response(client_socket, "玩家不存在", 404)
    except Exception as e:
        log_operation("KICK_PLAYER_ERROR", f"踢出玩家错误: {str(e)}", client_ip)
        send_error_response(client_socket, "踢出玩家失败", 500)

def handle_force_ready(request_data, client_socket, client_ip, token):
    """处理强制准备请求"""
    if not check_rate_limit(client_ip):
        send_error_response(client_socket, "操作过于频繁，请稍后再试", 429)
        return
    
    try:
        content_length = 0
        for line in request_data.split('\r\n'):
            if line.startswith('Content-Length:'):
                content_length = int(line.split(':')[1].strip())
                break
        
        if content_length > 0:
            body = request_data.split('\r\n\r\n')[1]
            while len(body) < content_length:
                body += client_socket.recv(1024).decode('utf-8')
            
            data = json.loads(body)
            room_id = data.get('roomId')
            user_id = data.get('userId')
            confirmed = data.get('confirmed', False)
            
            if not confirmed:
                send_error_response(client_socket, "请确认操作", 400)
                return
            
            result = admin_force_ready(room_id, user_id)
            
            if result["status"] == "0":
                log_operation("FORCE_READY", f"强制准备: {user_id} in {room_id}", client_ip)
                send_json_response(client_socket, {"status": "success", "message": "玩家已强制准备"})
            elif result["status"] == "1":
                send_error_response(client_socket, "房间不存在", 404)
            else:
                send_error_response(client_socket, "玩家不存在", 404)
    except Exception as e:
        log_operation("FORCE_READY_ERROR", f"强制准备错误: {str(e)}", client_ip)
        send_error_response(client_socket, "强制准备失败", 500)

def handle_request(client_socket):
    try:
        request_data = client_socket.recv(1024).decode('utf-8')
        if not request_data:
            return
        
        lines = request_data.split('\r\n')
        request_line = lines[0]
        method, path, protocol = request_line.split(' ')
        
        client_ip = get_client_ip(client_socket)
        
        # 解析路径
        parsed_url = urlparse(path)
        path = parsed_url.path
        
        # 检查会话令牌（除了登录和首页）
        token = None
        if path not in ['/', '/admin.html', '/api/admin/login']:
            auth_header = None
            for line in lines:
                if line.startswith('Authorization:'):
                    auth_header = line.split(':')[1].strip()
                    break
            
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header[7:]
            
            if not token or not is_session_valid(token):
                send_error_response(client_socket, "未授权访问", 401)
                return
        
        # 处理请求
        if method == 'GET':
            if path == '/' or path == '/admin.html':
                # 处理首页请求
                admin_path = os.path.join(CURRENT_DIR, 'admin.html')
                if os.path.exists(admin_path):
                    with open(admin_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    send_html_response(client_socket, html_content)
                else:
                    send_error_response(client_socket, "页面不存在", 404)
            elif path == '/api/admin/rooms':
                handle_get_rooms(client_socket, client_ip)
            elif path.startswith('/api/admin/room/'):
                room_id = path.split('/')[-1]
                handle_get_room_detail(room_id, client_socket, client_ip)
            else:
                send_error_response(client_socket, "未找到", 404)
        elif method == 'POST':
            if path == '/api/admin/login':
                handle_login(request_data, client_socket, client_ip)
            elif path == '/api/admin/destroy-room':
                handle_destroy_room(request_data, client_socket, client_ip, token)
            elif path == '/api/admin/kick-player':
                handle_kick_player(request_data, client_socket, client_ip, token)
            elif path == '/api/admin/force-ready':
                handle_force_ready(request_data, client_socket, client_ip, token)
            else:
                send_error_response(client_socket, "未找到", 404)
        else:
            send_error_response(client_socket, "方法不允许", 405)
    except Exception as e:
        print(f"Error handling request: {str(e)}")
        send_error_response(client_socket, "服务器错误", 500)
    finally:
        client_socket.close()

def start_admin_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    server_socket.bind(('', ADMIN_PORT))
    server_socket.listen(5)
    
    print(f"Admin server started at http://localhost:{ADMIN_PORT}")
    
    while True:
        client_socket, client_address = server_socket.accept()
        print(f"Received admin connection from {client_address}")
        client_thread = threading.Thread(target=handle_request, args=(client_socket,))
        client_thread.daemon = True
        client_thread.start()

def start_admin_server_thread():
    admin_thread = threading.Thread(target=start_admin_server, daemon=True)
    admin_thread.start()
    return admin_thread

if __name__ == '__main__':
    start_admin_server()