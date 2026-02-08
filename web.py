#!/usr/bin/env python3

import json
import threading
import os
import socket
from urllib.parse import urlparse, parse_qs

from room import get_all_rooms, get_room_detail

# 导入外部API客户端
try:
    import external_api_client
    external_api_available = True
except ImportError:
    external_api_available = False

# 获取当前文件的绝对路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

WEB_PORT = 8081

# 全局跨服务器管理器
inter_server_manager = None

# 外部API配置
EXTERNAL_API_URLS = [
    ""
]

def get_all_rooms_with_inter_server():
    """获取所有互联服务器的房间信息"""
    global inter_server_manager
    
    if inter_server_manager:
        # 获取本地和互联服务器的房间
        rooms = inter_server_manager.get_all_rooms()
    else:
        # 获取本地房间
        local_rooms_result = get_all_rooms()
        rooms = local_rooms_result.get('rooms', [])
    
    # 获取外部服务器的房间
    if external_api_available:
        api_client = external_api_client.get_external_api_client()
        for api_url in EXTERNAL_API_URLS:
            external_rooms = api_client.get_rooms_from_api(api_url)
            rooms.extend(external_rooms)
    
    return {
        "status": "0",
        "rooms": rooms
    }

def get_room_detail_with_inter_server(room_id):
    """获取房间详情，支持跨服务器"""
    global inter_server_manager
    
    if inter_server_manager:
        return inter_server_manager.get_room_detail_from_all_servers(room_id)
    else:
        return get_room_detail(room_id)

def set_inter_server_manager(manager):
    """设置跨服务器管理器"""
    global inter_server_manager
    inter_server_manager = manager

def handle_request(client_socket):
    try:
        # 接收请求数据
        request_data = client_socket.recv(1024).decode('utf-8')
        if not request_data:
            return
        
        # 解析请求
        lines = request_data.split('\r\n')
        request_line = lines[0]
        method, path, protocol = request_line.split(' ')
        
        # 解析路径
        parsed_url = urlparse(path)
        path = parsed_url.path
        
        # 处理请求
        if method == 'GET':
            if path == '/api/rooms':
                # 处理获取所有房间请求
                result = get_all_rooms_with_inter_server()
                response = f'HTTP/1.1 200 OK\r\n'
                response += f'Content-Type: application/json\r\n'
                response += f'Access-Control-Allow-Origin: *\r\n'
                response += f'Content-Length: {len(json.dumps(result))}\r\n'
                response += '\r\n'
                response += json.dumps(result)
                client_socket.sendall(response.encode('utf-8'))
            elif path.startswith('/api/room/'):
                # 处理获取房间详情请求
                room_id = path.split('/')[-1]
                result = get_room_detail_with_inter_server(room_id)
                response = f'HTTP/1.1 200 OK\r\n'
                response += f'Content-Type: application/json\r\n'
                response += f'Access-Control-Allow-Origin: *\r\n'
                response += f'Content-Length: {len(json.dumps(result))}\r\n'
                response += '\r\n'
                response += json.dumps(result)
                client_socket.sendall(response.encode('utf-8'))
            elif path == '/' or path == '/index.html':
                # 处理首页请求
                index_path = os.path.join(CURRENT_DIR, 'index.html')
                if os.path.exists(index_path):
                    with open(index_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    response = f'HTTP/1.1 200 OK\r\n'
                    response += f'Content-Type: text/html\r\n'
                    response += f'Content-Length: {len(html_content.encode("utf-8"))}\r\n'
                    response += '\r\n'
                    response += html_content
                    client_socket.sendall(response.encode('utf-8'))
                else:
                    response = 'HTTP/1.1 404 Not Found\r\n'
                    response += 'Content-Type: text/plain\r\n'
                    response += 'Content-Length: 9\r\n'
                    response += '\r\n'
                    response += 'Not Found'
                    client_socket.sendall(response.encode('utf-8'))
            else:
                # 处理其他请求
                response = 'HTTP/1.1 404 Not Found\r\n'
                response += 'Content-Type: text/plain\r\n'
                response += 'Content-Length: 9\r\n'
                response += '\r\n'
                response += 'Not Found'
                client_socket.sendall(response.encode('utf-8'))
        elif method == 'POST':
            if path == '/api/rooms/search':
                # 处理搜索房间请求
                # 解析请求体
                content_length = 0
                for line in lines:
                    if line.startswith('Content-Length:'):
                        content_length = int(line.split(':')[1].strip())
                        break
                
                if content_length > 0:
                    body = request_data.split('\r\n\r\n')[1]
                    while len(body) < content_length:
                        body += client_socket.recv(1024).decode('utf-8')
                    
                    search_params = json.loads(body)
                    all_rooms = get_all_rooms()['rooms']
                    filtered_rooms = all_rooms
                    
                    if 'roomId' in search_params and search_params['roomId']:
                        filtered_rooms = [room for room in filtered_rooms if search_params['roomId'] in room['roomId']]
                    
                    if 'state' in search_params and search_params['state']:
                        filtered_rooms = [room for room in filtered_rooms if room['state'] == search_params['state']]
                    
                    if 'locked' in search_params:
                        filtered_rooms = [room for room in filtered_rooms if room['locked'] == search_params['locked']]
                    
                    if 'live' in search_params:
                        filtered_rooms = [room for room in filtered_rooms if room['live'] == search_params['live']]
                    
                    if 'minUsers' in search_params:
                        filtered_rooms = [room for room in filtered_rooms if room['userCount'] >= search_params['minUsers']]
                    
                    if 'maxUsers' in search_params:
                        filtered_rooms = [room for room in filtered_rooms if room['userCount'] <= search_params['maxUsers']]
                    
                    result = {"status": "0", "rooms": filtered_rooms}
                    response = f'HTTP/1.1 200 OK\r\n'
                    response += f'Content-Type: application/json\r\n'
                    response += f'Access-Control-Allow-Origin: *\r\n'
                    response += f'Content-Length: {len(json.dumps(result))}\r\n'
                    response += '\r\n'
                    response += json.dumps(result)
                    client_socket.sendall(response.encode('utf-8'))
                else:
                    response = 'HTTP/1.1 400 Bad Request\r\n'
                    response += 'Content-Type: text/plain\r\n'
                    response += 'Content-Length: 11\r\n'
                    response += '\r\n'
                    response += 'Bad Request'
                    client_socket.sendall(response.encode('utf-8'))
            else:
                # 处理其他POST请求
                response = 'HTTP/1.1 404 Not Found\r\n'
                response += 'Content-Type: text/plain\r\n'
                response += 'Content-Length: 9\r\n'
                response += '\r\n'
                response += 'Not Found'
                client_socket.sendall(response.encode('utf-8'))
        else:
            # 处理其他HTTP方法
            response = 'HTTP/1.1 405 Method Not Allowed\r\n'
            response += 'Content-Type: text/plain\r\n'
            response += 'Content-Length: 18\r\n'
            response += '\r\n'
            response += 'Method Not Allowed'
            client_socket.sendall(response.encode('utf-8'))
    except Exception as e:
        print(f"Error handling request: {str(e)}")
        response = 'HTTP/1.1 500 Internal Server Error\r\n'
        response += 'Content-Type: text/plain\r\n'
        response += 'Content-Length: 21\r\n'
        response += '\r\n'
        response += 'Internal Server Error'
        try:
            client_socket.sendall(response.encode('utf-8'))
        except:
            pass
    finally:
        # 关闭连接
        client_socket.close()

def start_web_server():
    try:
        # 创建TCP套接字
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # 绑定地址和端口
        print(f"Attempting to bind web server to port {WEB_PORT}...")
        server_socket.bind(('', WEB_PORT))
        server_socket.listen(5)
        
        print(f"Web server started at http://localhost:{WEB_PORT}")
        
        # 处理请求
        while True:
            client_socket, client_address = server_socket.accept()
            print(f"Received connection from {client_address}")
            # 创建线程处理请求
            client_thread = threading.Thread(target=handle_request, args=(client_socket,))
            client_thread.daemon = True
            client_thread.start()
    except Exception as e:
        print(f"Error starting web server: {str(e)}")
        import traceback
        traceback.print_exc()

def start_web_server_thread():
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    return web_thread

if __name__ == '__main__':
    start_web_server()
