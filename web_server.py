from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import json
from data_manager import DataManager

class WebServer:
    def __init__(self, data_manager: DataManager, port=54321):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'your-secret-key-here'
        # 配置SocketIO以提高连接稳定性
        self.socketio = SocketIO(self.app, 
                               cors_allowed_origins="*",
                               logger=False,
                               engineio_logger=False,
                               ping_timeout=60,
                               ping_interval=25,
                               async_mode='threading')
        self.data_manager = data_manager
        self.port = port
        
        # 注册路由和事件
        self.setup_routes()
        self.setup_socket_events()
        
        # 注册为数据管理器的观察者
        self.data_manager.add_observer(self.on_data_manager_event)
        
    def setup_routes(self):
        """设置HTTP路由"""
        
        @self.app.route('/')
        def index():
            return render_template('index.html')
        
        @self.app.route('/api/ports')
        def get_ports():
            """获取可用端口列表"""
            ports = self.data_manager.get_available_ports()
            return jsonify(ports)
        
        @self.app.route('/api/history')
        def get_history():
            """获取发送历史"""
            history = self.data_manager.get_history()
            return jsonify(history)
        
        @self.app.route('/api/port/<port>/data')
        def get_port_data(port):
            """获取端口数据"""
            data = self.data_manager.get_port_data(port)
            return jsonify(data)
        
        @self.app.route('/api/port/<port>/settings', methods=['GET', 'POST'])
        def port_settings(port):
            """获取或设置端口配置"""
            if request.method == 'GET':
                settings = self.data_manager.get_port_settings(port)
                return jsonify(settings)
            else:
                settings = request.json
                self.data_manager.update_port_settings(port, settings)
                return jsonify({'success': True})

        @self.app.route('/api/port/<port>/name', methods=['GET', 'POST'])
        def port_name(port):
            """获取或设置端口名称"""
            if request.method == 'GET':
                name = self.data_manager.get_port_name(port)
                return jsonify({'name': name})
            else:
                data = request.json
                name = data.get('name', '')
                self.data_manager.update_port_name(port, name)
                return jsonify({'success': True})
    
    def setup_socket_events(self):
        """设置WebSocket事件"""
        
        @self.socketio.on('connect')
        def handle_connect():
            print(f"Client connected: {request.sid}")
            # 发送当前状态给新连接的客户端
            emit('ports_update', self.data_manager.get_available_ports())
            emit('history_update', self.data_manager.get_history())
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            print(f"Client disconnected: {request.sid}")
        
        @self.socketio.on('start_port')
        def handle_start_port(data):
            """启动端口监控"""
            port = data['port']
            success = self.data_manager.start_port_monitoring(port)
            emit('port_start_result', {
                'port': port,
                'success': success
            })
        
        @self.socketio.on('stop_port')
        def handle_stop_port(data):
            """停止端口监控"""
            port = data['port']
            success = self.data_manager.stop_port_monitoring(port)
            emit('port_stop_result', {
                'port': port,
                'success': success
            })
        
        @self.socketio.on('send_data')
        def handle_send_data(data):
            """发送数据"""
            port = data['port']
            hex_data = data['data']
            success = self.data_manager.send_data(port, hex_data)
            emit('send_result', {
                'port': port,
                'success': success,
                'data': hex_data
            })
        
        @self.socketio.on('clear_data')
        def handle_clear_data(data):
            """清除端口数据"""
            port = data['port']
            self.data_manager.clear_port_data(port)
        
        @self.socketio.on('request_port_data')
        def handle_request_port_data(data):
            """请求端口数据"""
            port = data['port']
            port_data = self.data_manager.get_port_data(port)
            emit('port_data', {
                'port': port,
                'data': port_data
            })

        @self.socketio.on('request_ports_update')
        def handle_request_ports_update():
            """请求端口列表更新"""
            emit('ports_update', self.data_manager.get_available_ports())

        @self.socketio.on('update_port_name')
        def handle_update_port_name(data):
            """更新端口名称"""
            port = data['port']
            name = data['name']
            self.data_manager.update_port_name(port, name)
            emit('port_name_updated', {
                'port': port,
                'name': name,
                'success': True
            })
    
    def on_data_manager_event(self, event_type: str, data):
        """处理数据管理器事件，广播给所有Web客户端"""
        try:
            if event_type == 'port_started':
                self.socketio.emit('port_started', data)
                self.socketio.emit('ports_update', self.data_manager.get_available_ports())
                
            elif event_type == 'port_stopped':
                self.socketio.emit('port_stopped', data)
                self.socketio.emit('ports_update', self.data_manager.get_available_ports())
                
            elif event_type == 'data_received':
                self.socketio.emit('data_received', data)
                
            elif event_type == 'data_sent':
                # 这里不发送raw_data，只发送格式化后的数据
                emit_data = {
                    'port': data['port'],
                    'data': data['data']
                }
                self.socketio.emit('data_sent', emit_data)
                
            elif event_type == 'data_cleared':
                self.socketio.emit('data_cleared', data)
                
            elif event_type == 'history_updated':
                self.socketio.emit('history_update', data['history'])
                
            elif event_type == 'settings_updated':
                self.socketio.emit('settings_updated', data)
                # 同时发送端口列表更新以刷新名称显示
                self.socketio.emit('ports_update', self.data_manager.get_available_ports())

            elif event_type == 'port_name_updated':
                self.socketio.emit('port_name_updated', data)
                # 发送端口列表更新以刷新名称显示
                self.socketio.emit('ports_update', self.data_manager.get_available_ports())
                
        except Exception as e:
            print(f"Error broadcasting event {event_type}: {e}")
    
    def run(self, debug=False):
        """运行Web服务器"""
        print(f"Starting web server on http://localhost:{self.port}")
        self.socketio.run(self.app, 
                         host='0.0.0.0', 
                         port=self.port, 
                         debug=debug,
                         use_reloader=False)  # 避免在线程中使用reloader
    
    def run_in_thread(self, debug=False):
        """在后台线程中运行Web服务器"""
        def run_server():
            self.run(debug=debug)
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        return thread