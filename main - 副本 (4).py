import sys
import os
import serial
import datetime
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLineEdit, QLabel,
                             QCheckBox, QFileDialog, QGridLayout, QComboBox)
from PyQt5.QtCore import QThread, pyqtSignal, QDateTime
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor, QPixmap

##1. 保存和加载历史记录

import os
import json

HISTORY_FILE = "send_history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

class SerialMonitorThread(QThread):
    new_data = pyqtSignal(str, str, str)  # (port, direction, data)

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.serial = serial.Serial()
        self.serial.port = port
        self.serial.baudrate = 9600
        self.serial.bytesize = serial.EIGHTBITS
        self.serial.parity = serial.PARITY_NONE
        self.serial.stopbits = serial.STOPBITS_ONE
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
        self.initUI()
        self.threads = {}
        self.code_library = self.load_code_library("code_library.txt")

    def initUI(self):
        self.setWindowTitle("多串口通信程序V1.2")
        self.setGeometry(100, 100, 1200, 800)

        main_layout = QVBoxLayout()

        # Load QSS stylesheet
        with open("style.qss", "r") as f:
            self.setStyleSheet(f.read())

        # Serial ports selection
        ports_layout = QHBoxLayout()
        self.port_checkboxes = {}
        self.port_labels = {}
        ports = serial.tools.list_ports.comports()
        for port in ports:
            cb = QCheckBox(port.device)
            cb.stateChanged.connect(self.toggle_monitoring)
            label = QLabel()
            ports_layout.addWidget(cb)
            ports_layout.addWidget(label)
            self.port_checkboxes[port.device] = cb
            self.port_labels[port.device] = label
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
                thread = SerialMonitorThread(port)
                thread.new_data.connect(self.update_text_edit)
                thread.start()
                self.threads[port] = thread
                self.update_port_label(port, True)
                self.add_port_widgets(port)
        else:  # Unchecked
            if port in self.threads:
                self.save_log(port)
                self.threads[port].stop()
                del self.threads[port]
                self.update_port_label(port, False)
                self.remove_port_widgets(port)

    def update_text_edit(self, port, direction, data):
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


if __name__ == '__main__':
    app = QApplication(sys.argv)
    monitor = MultiSerialMonitor()
    monitor.show()
    sys.exit(app.exec_())
