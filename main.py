import sys
import os
import serial
import datetime
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLineEdit, QLabel,
                             QCheckBox, QFileDialog, QGridLayout, QComboBox, QMessageBox)
from PyQt5.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QSpinBox
from PyQt5.QtCore import QThread, pyqtSignal, QDateTime, QTimer 
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor, QPixmap, QIcon, QPainter
import json
import re

from data_manager import DataManager
from web_server import WebServer

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

class PortSettingsDialog(QDialog):
    def __init__(self, port, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{port} 设置")
        self.settings = settings.copy()
        layout = QFormLayout(self)

        # 添加名称设置
        self.name_edit = QLineEdit()
        self.name_edit.setText(self.settings.get("name", ""))
        self.name_edit.setPlaceholderText("输入端口自定义名称...")
        layout.addRow("端口名称", self.name_edit)

        self.baudrate = QSpinBox()
        self.baudrate.setRange(1200, 115200)
        self.baudrate.setValue(self.settings.get("baudrate", 9600))
        layout.addRow("波特率", self.baudrate)

        self.bytesize = QComboBox()
        self.bytesize.addItems(["5", "6", "7", "8"])
        self.bytesize.setCurrentText(str(self.settings.get("bytesize", 8)))
        layout.addRow("数据位", self.bytesize)

        self.parity = QComboBox()
        self.parity.addItems(["N", "E", "O", "M", "S"])
        self.parity.setCurrentText(self.settings.get("parity", "N"))
        layout.addRow("校验", self.parity)

        self.stopbits = QComboBox()
        self.stopbits.addItems(["1", "1.5", "2"])
        self.stopbits.setCurrentText(str(self.settings.get("stopbits", 1)))
        layout.addRow("停止位", self.stopbits)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_settings(self):
        return {
            "name": self.name_edit.text().strip(),
            "baudrate": self.baudrate.value(),
            "bytesize": int(self.bytesize.currentText()),
            "parity": self.parity.currentText(),
            "stopbits": float(self.stopbits.currentText())
        }

class SerialMonitorThread(QThread):
    new_data = pyqtSignal(str, str, str)  # (port, direction, data)

    def __init__(self, port, settings=None, data_manager=None):
        super().__init__()
        self.port = port
        self.data_manager = data_manager
        self.serial = serial.Serial()
        self.serial.port = port
        if settings is None:
            settings = {}
        self.serial.baudrate = settings.get("baudrate", 9600)
        self.serial.bytesize = settings.get("bytesize", serial.EIGHTBITS)
        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
            "M": serial.PARITY_MARK,
            "S": serial.PARITY_SPACE
        }
        self.serial.parity = parity_map.get(settings.get("parity", "N"), serial.PARITY_NONE)
        self.serial.stopbits = settings.get("stopbits", serial.STOPBITS_ONE)
        self.serial.timeout = 0.1
        self.running = False

    def run(self):
        try:
            self.serial.open()
            self.running = True
            while self.running:
                if self.serial.in_waiting:
                    data = self.serial.read(self.serial.in_waiting)
                    hex_data = ' '.join(f'{byte:02X}' for byte in data)
                    timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss.zzz")
                    formatted_data = f'{timestamp} - {hex_data}'
                    
                    # 只通知GUI显示
                    self.new_data.emit(self.port, 'received', formatted_data)
                    
                    # 通知数据管理器（只存储原始hex_data，不包含时间戳）
                    if self.data_manager:
                        self.data_manager.add_port_data(self.port, 'received', hex_data)
        except serial.SerialException as e:
            print(f"Serial exception on port {self.port}: {e}")
        finally:
            if self.serial.is_open:
                self.serial.close()

    def stop(self):
        self.running = False
        self.wait()
        if self.serial.is_open:
            self.serial.close()

    def send_data(self, data):
        if self.serial.is_open:
            hex_data = data.replace(" ", "")
            byte_data = bytes.fromhex(hex_data)
            self.serial.write(byte_data)
            # GUI显示由数据管理器处理

class MultiSerialMonitor(QWidget):
    def __init__(self, data_manager: DataManager):
        super().__init__()
        # 使用图标文件（如果存在）
        if os.path.exists("serial.ico"):
            self.setWindowIcon(QIcon("serial.ico"))
        
        self.data_manager = data_manager
        self.threads = {}
        self.has_activity = {}
        
        # Web服务器状态标签
        self.web_status_label = QLabel("Web服务器: 未启动")
        self.web_status_label.setStyleSheet("color: red;")
        
        self.initUI()
        
        # 注册为数据管理器观察者
        self.data_manager.add_observer(self.on_data_manager_event)

        # 定时器：每24小时自动保存一次
        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self.save_all_active_logs)
        self.save_timer.start(24 * 60 * 60 * 1000)  # 24小时，单位ms

    def initUI(self):
        self.setWindowTitle("多串口通信程序V0.8 (Web版)")
        self.setGeometry(100, 100, 1200, 800)

        main_layout = QVBoxLayout()

        # 加载样式表（如果存在）
        if os.path.exists("style.qss"):
            with open("style.qss", "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

        # Web服务器状态和控制
        web_layout = QHBoxLayout()
        web_layout.addWidget(QLabel("Web访问:"))
        web_layout.addWidget(self.web_status_label)
        web_layout.addStretch()
        main_layout.addLayout(web_layout)

        # Serial ports selection
        ports_layout = QHBoxLayout()
        self.port_checkboxes = {}
        self.port_labels = {}
        self.port_settings_buttons = {} 
        ports = serial.tools.list_ports.comports()
        for idx, port in enumerate(ports):
            port_layout = QHBoxLayout()
            
            # 获取端口显示名称
            display_name = self.get_port_display_name(port.device)
            cb = QCheckBox(display_name)
            cb.setProperty('port_device', port.device)  # 存储实际端口名
            cb.stateChanged.connect(self.toggle_monitoring)
            
            label_pixmap = QLabel()
            self.port_checkboxes[port.device] = cb
            self.port_labels[port.device] = label_pixmap
            settings_btn = QPushButton("设置")
            settings_btn.clicked.connect(lambda checked, p=port.device: self.show_port_settings(p))
            self.port_settings_buttons[port.device] = settings_btn

            port_layout.addWidget(cb)
            port_layout.addWidget(label_pixmap)
            port_layout.addWidget(settings_btn)
            port_layout.setSpacing(2)
            
            if idx != len(ports) - 1:
                sep = QLabel("|")
                sep.setStyleSheet("color: gray; font-weight: bold; margin-left:4px; margin-right:4px;")
                port_layout.addWidget(sep)

            ports_layout.addLayout(port_layout)
            self.update_port_label(port.device, False)
        main_layout.addLayout(ports_layout)

        # Text edits and controls
        self.grid_layout = QGridLayout()
        self.text_edits = {}
        self.send_lines = {}
        self.send_buttons = {}
        self.clear_buttons = {}
        self.save_buttons = {}
        main_layout.addLayout(self.grid_layout)

        self.setLayout(main_layout)

    def get_port_display_name(self, port_device):
        """获取端口显示名称"""
        settings = self.data_manager.get_port_settings(port_device)
        port_name = settings.get("name", "").strip()
        if port_name:
            return f"{port_device} ({port_name})"
        return port_device

    def update_port_display_names(self):
        """更新所有端口的显示名称"""
        for port_device, checkbox in self.port_checkboxes.items():
            display_name = self.get_port_display_name(port_device)
            checkbox.setText(display_name)

    def show_port_settings(self, port):
        current_settings = self.data_manager.get_port_settings(port)
        dlg = PortSettingsDialog(port, current_settings, self)
        if dlg.exec_():
            new_settings = dlg.get_settings()
            self.data_manager.update_port_settings(port, new_settings)
            # 更新端口显示名称
            self.update_port_display_names()

    def toggle_monitoring(self, state):
        sender = self.sender()
        port = sender.property('port_device')  # 获取实际端口名
        if state == 2:  # Checked
            if port not in self.threads:
                settings = self.data_manager.get_port_settings(port)
                
                # 启动数据管理器中的端口监控
                if self.data_manager.start_port_monitoring(port):
                    # 启动串口线程
                    thread = SerialMonitorThread(port, settings, self.data_manager)
                    thread.new_data.connect(self.update_text_edit)
                    thread.start()
                    self.threads[port] = thread
                    self.update_port_label(port, True)
                    self.add_port_widgets(port)
                    self.has_activity[port] = False
        else:  # Unchecked
            if port in self.threads:
                # 停止串口线程
                self.save_log(port)
                self.threads[port].stop()
                del self.threads[port]
                
                # 停止数据管理器中的端口监控
                self.data_manager.stop_port_monitoring(port)
                
                self.update_port_label(port, False)
                self.remove_port_widgets(port)
                if port in self.has_activity:
                    del self.has_activity[port]

    def update_text_edit(self, port, direction, data):
        # 标记该串口有活动
        self.has_activity[port] = True

        if port in self.text_edits:
            # 为数据添加代码解析注释
            annotated_data = self.data_manager.annotate_data(data)
            
            text_edit = self.text_edits[port]
            cursor = text_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            format = QTextCharFormat()
            format.setForeground(QColor('black') if direction == 'received' else QColor('red'))
            cursor.insertText(f'{annotated_data}\n', format)
            text_edit.setTextCursor(cursor)

    def send_data(self, port, send_combo):
        data = send_combo.currentText()
        if data:
            # 通过数据管理器发送数据
            self.data_manager.send_data(port, data)
            
            # 更新GUI历史记录
            history = self.data_manager.get_history()
            send_combo.clear()
            send_combo.addItems(history)

    def on_data_manager_event(self, event_type: str, data):
        """处理数据管理器事件"""
        print(f"GUI received event: {event_type}, data: {data}")  # 调试信息
        
        if event_type == 'data_sent':
            # 实际发送数据到串口
            port = data['port']
            raw_data = data['raw_data']
            if port in self.threads:
                try:
                    if self.threads[port].serial.is_open:
                        self.threads[port].serial.write(raw_data)
                        
                        # 显示发送的数据（只在GUI显示，不重复添加到数据管理器）
                        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss.zzz")
                        formatted_data = f'{timestamp} - {data["data"]}'
                        self.update_text_edit(port, 'sent', formatted_data)
                except Exception as e:
                    print(f"Failed to send data to {port}: {e}")
        
        elif event_type == 'data_received':
            # 只有当数据不是来自本地串口线程时才显示（避免重复显示）
            # 这主要用于Web端发起的操作同步到GUI
            pass
        
        elif event_type == 'data_cleared':
            # 清除GUI显示
            port = data['port']
            if port in self.text_edits:
                self.text_edits[port].clear()

        elif event_type == 'settings_updated':
            # 设置更新时，刷新显示名称
            self.update_port_display_names()

    def save_log(self, port):
        file_path_dir = os.path.dirname("log/")
        if not os.path.exists(file_path_dir):
            os.makedirs(file_path_dir)
        
        if port in self.text_edits:
            text_edit = self.text_edits[port]
            log_content = text_edit.toPlainText()
            now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"{port}_{now}.log"
            
            if file_name:
                with open(os.path.join(file_path_dir, file_name), 'w', encoding="utf-8") as file:
                    file.write(log_content)

    def clear_log(self, port):
        self.data_manager.clear_port_data(port)

    def update_port_label(self, port, active):
        if port in self.port_labels:
            label = self.port_labels[port]
            pixmap = QPixmap(20, 20)
            pixmap.fill(QColor('transparent'))
            painter = QPainter(pixmap)
            color = QColor('red') if active else QColor('gray')
            painter.setBrush(color)
            painter.setPen(color)
            painter.drawEllipse(0, 0, 15, 15)
            painter.end()
            label.setPixmap(pixmap)

    def add_port_widgets(self, port):
        row = len(self.text_edits) // 2
        col = len(self.text_edits) % 2

        # 使用端口显示名称作为标签
        display_name = self.get_port_display_name(port)
        label = QLabel(display_name)
        label.setObjectName(f'label_{port}')
        self.grid_layout.addWidget(label, row * 3, col)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        self.grid_layout.addWidget(text_edit, row * 3 + 1, col)
        self.text_edits[port] = text_edit

        send_layout = QHBoxLayout()
        send_combo = QComboBox()
        send_combo.setEditable(True)
        history = self.data_manager.get_history()
        send_combo.addItems(history)
        
        send_button = QPushButton("发送")
        send_button.clicked.connect(lambda checked, p=port, l=send_combo: self.send_data(p, l))
        clear_button = QPushButton("清除")
        clear_button.clicked.connect(lambda checked, p=port: self.clear_log(p))
        save_button = QPushButton("保存")
        save_button.clicked.connect(lambda checked, p=port: self.save_log(p))
        
        send_layout.addWidget(send_combo)
        send_layout.addWidget(send_button)
        send_layout.addWidget(clear_button)
        send_layout.addWidget(save_button)

        self.grid_layout.addLayout(send_layout, row * 3 + 2, col)

        self.send_lines[port] = send_combo
        self.send_buttons[port] = send_button
        self.clear_buttons[port] = clear_button
        self.save_buttons[port] = save_button

    def remove_port_widgets(self, port):
        if port in self.text_edits:
            self.grid_layout.removeWidget(self.text_edits[port])
            self.text_edits[port].deleteLater()
            del self.text_edits[port]

        if port in self.send_lines:
            self.grid_layout.removeWidget(self.send_lines[port])
            self.send_lines[port].deleteLater()
            del self.send_lines[port]

        if port in self.send_buttons:
            self.grid_layout.removeWidget(self.send_buttons[port])
            self.send_buttons[port].deleteLater()
            del self.send_buttons[port]

        if port in self.clear_buttons:
            self.grid_layout.removeWidget(self.clear_buttons[port])
            self.clear_buttons[port].deleteLater()
            del self.clear_buttons[port]

        if port in self.save_buttons:
            self.grid_layout.removeWidget(self.save_buttons[port])
            self.save_buttons[port].deleteLater()
            del self.save_buttons[port]

        label_widget = self.findChild(QLabel, f'label_{port}')
        if label_widget:
            self.grid_layout.removeWidget(label_widget)
            label_widget.deleteLater()
        self.update()

    def save_all_active_logs(self):
        for port in list(self.threads.keys()):
            if self.has_activity.get(port, False):
                self.save_log(port)
                self.has_activity[port] = False

    def update_web_status(self, running=True, url=""):
        if running:
            self.web_status_label.setText(f"运行中 - {url}")
            self.web_status_label.setStyleSheet("color: green;")
        else:
            self.web_status_label.setText("未启动")
            self.web_status_label.setStyleSheet("color: red;")

    def closeEvent(self, event):
        for port in list(self.threads.keys()):
            self.save_log(port)
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 创建数据管理器
    data_manager = DataManager()
    
    # 创建主界面
    monitor = MultiSerialMonitor(data_manager)
    monitor.show()
    
    # 启动Web服务器
    try:
        web_server = WebServer(data_manager, port=54321)
        web_thread = web_server.run_in_thread(debug=False)
        monitor.update_web_status(True, "http://localhost:54321")
        
        print("Web服务器已启动，访问地址: http://localhost:54321")
        print("可以通过浏览器或手机访问该地址进行远程控制")
        
    except Exception as e:
        print(f"Web服务器启动失败: {e}")
        QMessageBox.warning(monitor, "警告", f"Web服务器启动失败: {e}")
    
    sys.exit(app.exec_())