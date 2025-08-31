import sys
import os
import serial
import datetime
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLineEdit, QLabel,
                             QCheckBox, QFileDialog, QGridLayout, QComboBox)
from PyQt5.QtWidgets import QDialog, QFormLayout, QDialogButtonBox, QSpinBox
from PyQt5.QtCore import QThread, pyqtSignal, QDateTime, QTimer 
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor, QPixmap
import json

# 发送历史记录
HISTORY_FILE = "send_history.json"
# 端口设置文件
COM_SETTINGS_FILE = "comsettings.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

def load_com_settings():
    if os.path.exists(COM_SETTINGS_FILE):
        with open(COM_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_com_settings(settings):
    with open(COM_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

class PortSettingsDialog(QDialog):
    def __init__(self, port, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{port} 设置")
        self.settings = settings.copy()
        layout = QFormLayout(self)

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
            "baudrate": self.baudrate.value(),
            "bytesize": int(self.bytesize.currentText()),
            "parity": self.parity.currentText(),
            "stopbits": float(self.stopbits.currentText())
        }

class SerialMonitorThread(QThread):
    new_data = pyqtSignal(str, str, str)  # (port, direction, data)

    def __init__(self, port, settings=None):
        super().__init__()
        self.port = port
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
                    self.new_data.emit(self.port, 'received', f'{timestamp} - {hex_data}')
        except serial.SerialException as e:
            print(f"Serial exception on port {self.port}: {e}")
        finally:
            self.serial.close()

    def stop(self):
        self.running = False
        self.wait()
        self.serial.close()

    def send_data(self, data):
        if self.serial.is_open:
            hex_data = data.replace(" ", "")
            byte_data = bytes.fromhex(hex_data)
            self.serial.write(byte_data)
            formatted_data = ' '.join(f'{byte:02X}' for byte in byte_data)
            timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss.zzz")
            self.new_data.emit(self.port, 'sent', f'{timestamp} - {formatted_data}')


class MultiSerialMonitor(QWidget):
    def __init__(self):
        super().__init__()
        self.history = load_history()
        self.com_settings = load_com_settings()
        self.initUI()
        self.threads = {}
        self.code_library = self.load_code_library("code_library.txt")
        self.has_activity = {}  # 新增：记录串口是否有收发数据

        # 定时器：每24小时自动保存一次
        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self.save_all_active_logs)
        self.save_timer.start(24 * 60 * 60 * 1000)  # 24小时，单位ms


    def initUI(self):
        self.setWindowTitle("多串口通信程序V0.6")
        self.setGeometry(100, 100, 1200, 800)

        main_layout = QVBoxLayout()

        # Load QSS stylesheet
        with open("style.qss", "r") as f:
            self.setStyleSheet(f.read())

        # Serial ports selection
        ports_layout = QHBoxLayout()
        self.port_checkboxes = {}
        self.port_labels = {}
        self.port_settings_buttons = {}  # 新增
        ports = serial.tools.list_ports.comports()
        for port in ports:
            cb = QCheckBox(port.device)
            cb.stateChanged.connect(self.toggle_monitoring)
            label = QLabel()
            settings_btn = QPushButton("设置")
            settings_btn.clicked.connect(lambda checked, p=port.device: self.show_port_settings(p))
            ports_layout.addWidget(cb)
            ports_layout.addWidget(label)
            ports_layout.addWidget(settings_btn)
            self.port_checkboxes[port.device] = cb
            self.port_labels[port.device] = label
            self.port_settings_buttons[port.device] = settings_btn
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

    def show_port_settings(self, port):
        current_settings = self.com_settings.get(port, {})
        dlg = PortSettingsDialog(port, current_settings, self)
        if dlg.exec_():
            self.com_settings[port] = dlg.get_settings()
            save_com_settings(self.com_settings)

    def load_code_library(self, file_path):
        code_library = {}
        with open(file_path, "r", encoding="utf-8") as file:
            for line in file:
                hex_data, comment = line.strip().split('#')
                code_library[hex_data.strip()] = comment.strip()
        return code_library

    def annotate_data(self, data):
        annotations = []
        for hex_data, comment in self.code_library.items():
            if hex_data in data:
                annotations.append(comment)
        if annotations:
            data += ' (' + ', '.join(annotations) + ')'
        return data

    def toggle_monitoring(self, state):
        sender = self.sender()
        port = sender.text()
        if state == 2:  # Checked
            if port not in self.threads:
                settings = self.com_settings.get(port, {})
                settings = self.com_settings.get(port, {})
                thread = SerialMonitorThread(port, settings)
                thread.new_data.connect(self.update_text_edit)
                thread.start()
                self.threads[port] = thread
                self.update_port_label(port, True)
                self.add_port_widgets(port)
                self.has_activity[port] = False
        else:  # Unchecked
            if port in self.threads:
                self.save_log(port)
                self.threads[port].stop()
                del self.threads[port]
                self.update_port_label(port, False)
                self.remove_port_widgets(port)
                if port in self.has_activity:
                    del self.has_activity[port]

    def update_text_edit(self, port, direction, data):
        # 标记该串口有活动
        self.has_activity[port] = True

        annotated_data = self.annotate_data(data)
        text_edit = self.text_edits[port]
        cursor = text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        format = QTextCharFormat()
        format.setForeground(QColor('black') if direction == 'received' else QColor('red'))
        cursor.insertText(f'{annotated_data}\n', format)
        text_edit.setTextCursor(cursor)

    def send_data(self, port, send_combo):
        data = send_combo.currentText()
        if data not in self.history:
            #格式化
            data= data.replace(" ", "")
            data= data.upper()
            f_data=bytes.fromhex(data)
            data= ' '.join(f'{byte:02X}' for byte in f_data)
            #增加历史
            self.history.append(data)
            send_combo.addItem(data)
            save_history(self.history)
        if data:
            self.threads[port].send_data(data)
            #send_line.clear()

    def save_log(self, port):
        file_path_dir = os.path.dirname("log/")
        if not os.path.exists(file_path_dir):
            # 目录不存在创建，makedirs可以创建多级目录
            os.makedirs(file_path_dir)
        text_edit = self.text_edits[port]
        log_content = text_edit.toPlainText()
        #if log_content.strip():  # 只有在显示框内有内容时才保存
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{port}_{now}.log"
        #options = QFileDialog.Options()
        #file_name, _ = QFileDialog.getSaveFileName(self, "Save Log", "", "Text Files (*.txt);;All Files (*)",
        #                                           options=options)
        if file_name:
            with open(os.path.join(file_path_dir,file_name), 'w', encoding="utf-8") as file:
                file.write(log_content)

    def clear_log(self, port):
        self.text_edits[port].clear()

    def update_port_label(self, port, active):
        label = self.port_labels[port]
        pixmap = QPixmap(10, 10)
        pixmap.fill(QColor('green') if active else QColor('gray'))
        label.setPixmap(pixmap)

    def add_port_widgets(self, port):
        row = len(self.text_edits) // 2
        col = len(self.text_edits) % 2

        label = QLabel(port)
        label.setObjectName(f'label_{port}')
        self.grid_layout.addWidget(label, row * 3, col)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        self.grid_layout.addWidget(text_edit, row * 3 + 1, col)
        self.text_edits[port] = text_edit

        send_layout = QHBoxLayout()
        send_combo = QComboBox()
        send_combo.setEditable(True)
        send_combo.addItems(self.history)
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
        # 定时保存所有有活动的串口日志
        for port in list(self.threads.keys()):
            if self.has_activity.get(port, False):
                self.save_log(port)
                self.has_activity[port] = False  # 保存后重置活动标记


if __name__ == '__main__':
    app = QApplication(sys.argv)
    monitor = MultiSerialMonitor()
    monitor.show()
    sys.exit(app.exec_())
