import json
import os
import datetime
import serial
import serial.tools.list_ports
from threading import Lock
from typing import Dict, List, Callable, Any

class DataManager:
    """数据管理层，负责串口状态、历史记录等的统一管理"""
    
    def __init__(self):
        self.lock = Lock()
        self.port_states = {}  # 端口状态
        self.port_data = {}    # 端口数据
        self.history = self.load_history()
        self.com_settings = self.load_com_settings()
        self.code_library = self.load_code_library("code_library.txt")
        self.observers = []    # 观察者列表，用于通知界面更新
        
    def add_observer(self, callback: Callable):
        """添加观察者"""
        self.observers.append(callback)
        
    def remove_observer(self, callback: Callable):
        """移除观察者"""
        if callback in self.observers:
            self.observers.remove(callback)
            
    def notify_observers(self, event_type: str, data: Any):
        """通知所有观察者"""
        print(f"DataManager notifying observers: {event_type}, observers count: {len(self.observers)}")  # 调试信息
        for callback in self.observers:
            try:
                callback(event_type, data)
            except Exception as e:
                print(f"Observer notification error: {e}")
    
    def get_available_ports(self) -> List[Dict]:
        """获取可用端口列表"""
        ports = []
        for port in serial.tools.list_ports.comports():
            port_settings = self.com_settings.get(port.device, {})
            port_name = port_settings.get("name", "").strip()
            
            # 创建显示名称
            display_name = f"{port.device} ({port_name})" if port_name else port.device
            
            ports.append({
                'device': port.device,
                'name': port_name,
                'display_name': display_name,
                'description': port.description,
                'active': port.device in self.port_states
            })
        return ports
    
    def start_port_monitoring(self, port: str) -> bool:
        """启动端口监控"""
        with self.lock:
            if port in self.port_states:
                return False
                
            settings = self.com_settings.get(port, {})
            try:
                self.port_states[port] = {
                    'active': True,
                    'settings': settings
                }
                self.port_data[port] = []
                
                self.notify_observers('port_started', {
                    'port': port,
                    'settings': settings
                })
                return True
            except Exception as e:
                print(f"Failed to start monitoring port {port}: {e}")
                return False
    
    def stop_port_monitoring(self, port: str) -> bool:
        """停止端口监控"""
        with self.lock:
            if port not in self.port_states:
                return False
                
            del self.port_states[port]
            if port in self.port_data:
                del self.port_data[port]
                
            self.notify_observers('port_stopped', {'port': port})
            return True
    
    def add_port_data(self, port: str, direction: str, data: str):
        """添加端口数据"""
        with self.lock:
            if port not in self.port_data:
                self.port_data[port] = []
            
            # 为原始hex数据添加注释
            annotated_data = self.annotate_data(data)
            
            # 生成时间戳
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            # 组合完整数据
            full_data = f"{timestamp} - {annotated_data}"
            
            entry = {
                'direction': direction,
                'data': full_data,
                'timestamp': timestamp
            }
            
            self.port_data[port].append(entry)
            
            # 限制数据条数，避免内存占用过大
            if len(self.port_data[port]) > 1000:
                self.port_data[port] = self.port_data[port][-1000:]
                
            self.notify_observers('data_received', {
                'port': port,
                'entry': entry
            })
    
    def send_data(self, port: str, data: str) -> bool:
        """发送数据"""
        try:
            # 格式化数据
            formatted_data = data.replace(" ", "").upper()
            byte_data = bytes.fromhex(formatted_data)
            formatted_data = ' '.join(f'{byte:02X}' for byte in byte_data)
            
            # 添加到历史记录
            if formatted_data not in self.history:
                self.history.insert(0, formatted_data)
                if len(self.history) > 100:  # 限制历史记录条数
                    self.history = self.history[:100]
                self.save_history(self.history)
                
                self.notify_observers('history_updated', {
                    'history': self.history
                })
            
            # 添加到数据记录
            self.add_port_data(port, 'sent', formatted_data)
            
            # 通知发送事件
            self.notify_observers('data_sent', {
                'port': port,
                'data': formatted_data,
                'raw_data': byte_data
            })
            
            return True
        except Exception as e:
            print(f"Failed to send data: {e}")
            return False
    
    def get_port_data(self, port: str) -> List[Dict]:
        """获取端口数据"""
        with self.lock:
            return self.port_data.get(port, []).copy()
    
    def clear_port_data(self, port: str):
        """清除端口数据"""
        with self.lock:
            if port in self.port_data:
                self.port_data[port] = []
                self.notify_observers('data_cleared', {'port': port})
    
    def get_history(self) -> List[str]:
        """获取发送历史"""
        return self.history.copy()
    
    def update_port_settings(self, port: str, settings: Dict):
        """更新端口设置"""
        self.com_settings[port] = settings
        self.save_com_settings(self.com_settings)
        
        if port in self.port_states:
            self.port_states[port]['settings'] = settings
            
        self.notify_observers('settings_updated', {
            'port': port,
            'settings': settings
        })
    
    def get_port_settings(self, port: str) -> Dict:
        """获取端口设置"""
        return self.com_settings.get(port, {
            "name": "",
            "baudrate": 9600,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1.0
        })

    def update_port_name(self, port: str, name: str):
        """更新端口名称"""
        if port not in self.com_settings:
            self.com_settings[port] = {
                "baudrate": 9600,
                "bytesize": 8,
                "parity": "N",
                "stopbits": 1.0
            }
        
        self.com_settings[port]["name"] = name.strip()
        self.save_com_settings(self.com_settings)
        
        self.notify_observers('port_name_updated', {
            'port': port,
            'name': name
        })

    def get_port_name(self, port: str) -> str:
        """获取端口名称"""
        return self.com_settings.get(port, {}).get("name", "")

    def get_port_display_name(self, port: str) -> str:
        """获取端口显示名称"""
        port_name = self.get_port_name(port)
        if port_name:
            return f"{port} ({port_name})"
        return port
    
    # 原有的辅助方法
    def load_history(self):
        """加载发送历史"""
        history_file = "send_history.json"
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    return history[::-1]  # 反转列表，最新的在前面
            except (json.JSONDecodeError, OSError) as e:
                print(f"Error loading history: {e}")
                return []
        return []

    def save_history(self, history):
        """保存发送历史"""
        history_file = "send_history.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)

    def load_com_settings(self):
        """加载串口设置"""
        com_settings_file = "comsettings.json"
        if os.path.exists(com_settings_file):
            with open(com_settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_com_settings(self, settings):
        """保存串口设置"""
        com_settings_file = "comsettings.json"
        with open(com_settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
    
    def load_code_library(self, file_path):
        """加载代码库"""
        import re
        code_library = {}
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                for line_num, line in enumerate(file, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    try:
                        if '#' in line:
                            hex_data, comment = line.split('#', 1)
                            hex_data = hex_data.strip()
                            comment = comment.strip()
                            
                            if '*' in hex_data:
                                # 包含通配符的模式
                                regex_pattern = self.pattern_to_regex(hex_data)
                                code_library[hex_data] = {
                                    'comment': comment,
                                    'regex': re.compile(regex_pattern),
                                    'is_pattern': True
                                }
                            else:
                                # 精确匹配模式
                                code_library[hex_data] = {
                                    'comment': comment,
                                    'regex': None,
                                    'is_pattern': False
                                }
                    except Exception as e:
                        print(f"解析代码库第{line_num}行时出错: {line}, 错误: {e}")
                        continue
        except Exception as e:
            print(f"加载代码库文件失败: {e}")
            
        return code_library
    
    def pattern_to_regex(self, pattern):
        """将包含通配符'*'的模式转换为正则表达式"""
        import re
        escaped_pattern = re.escape(pattern)
        regex_pattern = escaped_pattern.replace(r'\*', r'[0-9A-F]{2}')
        return regex_pattern
    
    def annotate_data(self, data):
        """为数据添加注释"""
        annotations = []
        
        # 移除时间戳，只对16进制数据部分进行匹配
        hex_part = data
        if ' - ' in data:
            hex_part = data.split(' - ', 1)[1] if len(data.split(' - ', 1)) > 1 else data
        
        for pattern, pattern_info in self.code_library.items():
            try:
                if pattern_info['is_pattern']:
                    # 使用正则表达式匹配
                    if pattern_info['regex'] and pattern_info['regex'].search(hex_part):
                        annotations.append(f"{pattern_info['comment']} (匹配模式: {pattern})")
                else:
                    # 精确字符串匹配
                    if pattern in hex_part:
                        annotations.append(pattern_info['comment'])
            except Exception as e:
                print(f"匹配模式时出错: {pattern}, 错误: {e}")
                continue
        
        if annotations:
            data += ' (' + ', '.join(annotations) + ')'
        return data