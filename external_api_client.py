#!/usr/bin/env python3

import json
import logging
import urllib.request
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class ExternalApiClient:
    """外部API客户端，用于获取非py端phira服务器的房间信息"""
    
    def __init__(self):
        self.cache = {}
        self.cache_time = {}
        self.cache_timeout = 30  # 缓存30秒
    
    def get_rooms_from_api(self, api_url: str) -> List[Dict]:
        """从外部API获取房间信息"""
        try:
            logger.info(f"Fetching rooms from external API: {api_url}")
            
            # 发送请求
            response = urllib.request.urlopen(api_url, timeout=10)
            data = response.read().decode('utf-8')
            api_data = json.loads(data)
            
            # 转换格式
            rooms = self._convert_api_format(api_data)
            logger.info(f"Fetched {len(rooms)} rooms from external API")
            return rooms
        except Exception as e:
            logger.error(f"Error fetching rooms from external API: {e}")
            return []
    
    def _convert_api_format(self, api_data: Dict) -> List[Dict]:
        """将外部API格式转换为项目内部格式"""
        converted_rooms = []
        
        # 外部API格式:
        # {
        #   "serverName": "FunXLink Studio",
        #   "onlinePlayers": 1,
        #   "roomCount": 1,
        #   "rooms": [
        #     {
        #       "id": "1",
        #       "name": "1",
        #       "playerCount": 1,
        #       "maxPlayers": 8,
        #       "state": {
        #         "type": "SelectChart",
        #         "chartId": null,
        #         "chartName": null
        #       },
        #       "locked": false,
        #       "cycle": false,
        #       "players": [
        #         {
        #           "id": 594089,
        #           "name": "Xiyv_"
        #         }
        #       ]
        #     }
        #   ]
        # }
        
        # 项目内部格式:
        # {
        #   "roomId": "roomId",
        #   "host": "hostId",
        #   "state": "SelectChart",
        #   "locked": false,
        #   "live": false,
        #   "cycle": false,
        #   "userCount": 1,
        #   "monitorCount": 0,
        #   "chart": null,
        #   "users": {
        #     "userId": {
        #       "id": "userId",
        #       "name": "userName"
        #     }
        #   },
        #   "server_id": "external_server",
        #   "server_name": "external_server_name"
        # }
        
        server_name = api_data.get('serverName', 'External Server')
        
        for room in api_data.get('rooms', []):
            # 转换用户信息
            users_info = {}
            for player in room.get('players', []):
                user_id = player.get('id')
                users_info[user_id] = {
                    "id": user_id,
                    "name": player.get('name', 'Unknown')
                }
            
            # 转换房间信息
            converted_room = {
                "roomId": room.get('id', 'unknown'),
                "host": room.get('players', [])[0].get('id') if room.get('players') else None,  # 假设第一个玩家是房主
                "state": room.get('state', {}).get('type', 'Unknown'),
                "locked": room.get('locked', False),
                "live": False,  # 外部API没有提供live字段
                "cycle": room.get('cycle', False),
                "userCount": room.get('playerCount', 0),
                "monitorCount": 0,  # 外部API没有提供monitorCount字段
                "chart": room.get('state', {}).get('chartId'),
                "users": users_info,
                "server_id": "external_server",
                "server_name": server_name
            }
            
            converted_rooms.append(converted_room)
        
        return converted_rooms
    
    def get_combined_rooms(self, local_rooms: List[Dict], external_api_urls: List[str]) -> List[Dict]:
        """获取本地房间和外部房间的组合列表"""
        combined_rooms = local_rooms.copy()
        
        for api_url in external_api_urls:
            external_rooms = self.get_rooms_from_api(api_url)
            combined_rooms.extend(external_rooms)
        
        return combined_rooms

# 全局实例
external_api_client = ExternalApiClient()

def get_external_api_client() -> ExternalApiClient:
    """获取外部API客户端实例"""
    return external_api_client
