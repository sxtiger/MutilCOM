import sys
import time
import serial
import threading
import json
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox


class RS485Monitor(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.devices = []
        self.device_threads = {}
        self.load_devices()

    def initUI(self):
        self.setWindowTitle('监控表')

        # Layouts
        self.main_layout = QVBoxLayout()

        # Device Input Fields
        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText('参数名称')
        self.query_input = QLineEdit(self)
        self.query_input.setPlaceholderText('查询数据')
        self.interval_input = QLineEdit(self)
        self.interval_input.setPlaceholderText('查询间隔(秒)')
        self.formula_input = QLineEdit(self)
        self.formula_input.setPlaceholderText('处理公式')
        self.unit_input = QLineEdit(self)
        self.unit_input.setPlaceholderText('单位')

        self.add_device_button = QPushButton('Add Device', self)
        self.add_device_button.clicked.connect(self.add_device)

        # Device Display Area
        self.device_layout = QVBoxLayout()

        # Add elements to main layout
        self.main_layout.addWidget(self.name_input)
        self.main_layout.addWidget(self.query_input)
        self.main_layout.addWidget(self.interval_input)
        self.main_layout.addWidget(self.formula_input)
        self.main_layout.addWidget(self.unit_input)
        self.main_layout.addWidget(self.add_device_button)
        self.main_layout.addLayout(self.device_layout)

        self.setLayout(self.main_layout)

        # Serial setup
        self.serial_port = None
        self.run_flag = True

        # Open COM port
        self.com_port = 'COM5'  # Use COM5 as the default COM port
        self.baud_rate = 9600
        self.open_serial_port()

    def open_serial_port(self):
        try:
            self.serial_port = serial.Serial(self.com_port, self.baud_rate, timeout=1)
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to open COM port: {e}')

    def add_device(self):
        name = self.name_input.text()
        query = self.query_input.text()
        interval = self.interval_input.text()
        formula = self.formula_input.text()
        unit = self.unit_input.text()

        if not name or not query or not interval or not formula or not unit:
            QMessageBox.warning(self, 'Input Error', 'All fields are required.')
            return

        try:
            interval = int(interval)
        except ValueError:
            QMessageBox.warning(self, 'Input Error', 'Interval must be an integer.')
            return

        device = {
            'name': name,
            'query': query,
            'interval': interval,
            'formula': formula,
            'unit': unit,
            'last_update': 0
        }
        self.devices.append(device)
        self.save_devices()

        # Create display
        device_widget = QWidget()
        layout = QHBoxLayout()

        name_label = QLabel(name)
        value_label = QLabel('0')
        unit_label = QLabel(unit)
        remove_button = QPushButton('Remove', self)

        layout.addWidget(name_label)
        layout.addWidget(value_label)
        layout.addWidget(unit_label)
        layout.addWidget(remove_button)

        device_widget.setLayout(layout)
        self.device_layout.addWidget(device_widget)

        # Remove device action
        remove_button.clicked.connect(lambda: self.remove_device(device, device_widget))

        # Start monitoring
        device_thread = threading.Thread(target=self.monitor_device, args=(device, value_label))
        device_thread.start()
        self.device_threads[name] = device_thread

    def monitor_device(self, device, value_label):
        while self.run_flag:
            current_time = time.time()
            if current_time - device['last_update'] >= device['interval'] :
                try:
                    # Send query
                    self.serial_port.write(bytes.fromhex(device['query']))
                    time.sleep(1)  # Wait for response

                    # Read response
                    response = self.serial_port.read_all().hex()
                    if response:
                        # Parse response using formula
                        result = self.parse_hex_data(response, device['formula'])
                        if result is not None:
                            value_label.setText(str(result))
                except Exception as e:
                    value_label.setText('Error')

                device['last_update'] = current_time

            time.sleep(1)

    def parse_hex_data(self, hex_data, formula):
        """
        解析十六进制数据并根据公式计算结果
        :param hex_data: 接收到的十六进制数据字符串
        :param formula: 解析公式
        :return: 解析结果
        """
        # 将十六进制字符串转换为字节数组
        data = bytes.fromhex(hex_data)

        # 自定义局部变量，以便在公式中使用
        local_vars = {}

        def extract_data(start, length):
            # 提取指定位置的字节数据，并转换为整数
            segment = data[start:start + length]
            return int.from_bytes(segment, byteorder='big')

        # 解析公式中的索引和长度，并提取数据
        while '[' in formula and ']' in formula:
            start = formula.find('[')
            end = formula.find(']')
            if start != -1 and end != -1:
                index_length = formula[start + 1:end]
                index, length = map(int, index_length.split(','))
                value = extract_data(index, length)
                formula = formula.replace(f'[{index},{length}]', str(value))

        # 计算公式结果
        try:
            result = eval(formula, {"__builtins__": None}, local_vars)
            return result
        except Exception as e:
            print(f"Error parsing formula: {e}")
            return None

    def remove_device(self, device, device_widget):
        self.devices.remove(device)
        self.save_devices()
        self.device_layout.removeWidget(device_widget)
        device_widget.deleteLater()
        self.run_flag = False

        if device['name'] in self.device_threads:
            self.device_threads[device['name']].join()
            del self.device_threads[device['name']]
        self.run_flag = True

    def load_devices(self):
        try:
            with open('devices.json', 'r', encoding='utf-8') as f:
                self.devices = json.load(f)
                for device in self.devices:
                    self.add_device_from_file(device)
        except FileNotFoundError:
            pass

    def save_devices(self):
        with open('devices.json', 'w', encoding='utf-8') as f:
            json.dump(self.devices, f, ensure_ascii=False, indent=4)

    def add_device_from_file(self, device):
        # Create display
        device_widget = QWidget()
        layout = QHBoxLayout()

        name_label = QLabel(device['name'])
        value_label = QLabel('0')
        unit_label = QLabel(device['unit'])
        remove_button = QPushButton('Remove', self)

        layout.addWidget(name_label)
        layout.addWidget(value_label)
        layout.addWidget(unit_label)
        layout.addWidget(remove_button)

        device_widget.setLayout(layout)
        self.device_layout.addWidget(device_widget)

        # Remove device action
        remove_button.clicked.connect(lambda: self.remove_device(device, device_widget))

        # Start monitoring
        device_thread = threading.Thread(target=self.monitor_device, args=(device, value_label))
        device_thread.start()
        self.device_threads[device['name']] = device_thread

    def closeEvent(self, event):
        self.run_flag = False
        for thread in self.device_threads.values():
            thread.join()
        if self.serial_port:
            self.serial_port.close()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    monitor = RS485Monitor()
    monitor.show()
    sys.exit(app.exec_())
