"""
settings_dialog.py - 设置窗口

简单直接的实现
"""
import asyncio
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QPushButton, QLabel, QComboBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QMessageBox, QGroupBox,
    QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from core.logger import logger


class SettingsDialog(QDialog):
    """设置窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        
        # 设置窗口大小
        self.setMinimumSize(600, 500)
        self.resize(700, 600)
        
        self._load_config()
        self._create_ui()

    def _load_config(self):
        try:
            from config import config_manager, secure_storage
            self.config_manager = config_manager
            self.secure_storage = secure_storage
            self.current_config = config_manager.all()
            self.has_api_key = secure_storage.has_api_key()
        except Exception as e:
            logger.error(f"[Settings] Failed to load config: {e}")
            self.current_config = {}
            self.has_api_key = False

    def _create_ui(self):
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # 创建选项卡
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_llm_tab(), "AI 模型")
        self.tabs.addTab(self._create_embedding_tab(), "记忆模型")
        self.tabs.addTab(self._create_appearance_tab(), "外观")
        self.tabs.addTab(self._create_behavior_tab(), "行为")
        
        main_layout.addWidget(self.tabs, 1)
        
        # 按钮区
        button_layout = QHBoxLayout()
        
        # 提示标签
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #28a745;")
        button_layout.addWidget(self.status_label)
        
        button_layout.addStretch()
        
        # 统一按钮样式和大小
        btn_width = 100
        btn_height = 36
        common_style = "border-radius: 4px; border: 1px solid #d1d1d6; font-size: 14px;"
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(btn_width, btn_height)
        cancel_btn.setStyleSheet(f"background-color: white; color: #333; {common_style}")
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("保存")
        save_btn.setFixedSize(btn_width, btn_height)
        save_btn.setStyleSheet(f"background-color: #007aff; color: white; border: none; {common_style}")
        save_btn.clicked.connect(self._save_settings)
        
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        
        main_layout.addLayout(button_layout)

    def _create_llm_tab(self) -> QWidget:
        """创建 AI 模型配置选项卡"""
        # 使用 QScrollArea 包裹内容，避免被挤压
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # API Key 组
        api_group = QGroupBox("API Key")
        api_layout = QFormLayout(api_group)
        api_layout.setHorizontalSpacing(15)
        api_layout.setVerticalSpacing(10)
        api_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setMinimumWidth(300)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("输入 API Key")
        if self.has_api_key:
            # 读取真实 API Key 并遮蔽显示
            real_key = self.secure_storage.load_api_key() or ""
            masked_key = self._mask_api_key(real_key)
            self.api_key_input.setText(masked_key)
            self.api_key_input.setPlaceholderText("留空保持不变")
            # 记录原始值，用于判断是否修改
            self._original_api_key = real_key
        else:
            self._original_api_key = ""
        
        api_layout.addRow("API Key:", self.api_key_input)
        
        # 显示/隐藏密码按钮
        toggle_btn = QPushButton("显示")
        toggle_btn.setCheckable(True)
        toggle_btn.setFixedWidth(60)
        toggle_btn.toggled.connect(self._toggle_api_key)
        api_layout.addRow("", toggle_btn)
        
        layout.addWidget(api_group)
        
        # 模型配置组
        model_group = QGroupBox("模型配置")
        model_layout = QFormLayout(model_group)
        model_layout.setHorizontalSpacing(15)
        model_layout.setVerticalSpacing(10)
        model_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # 对话模型
        self.chat_provider = QComboBox()
        self.chat_provider.setMinimumWidth(300)
        self.chat_provider.addItems(["deepseek", "openai", "anthropic", "qwen", "custom"])
        self.chat_provider.setCurrentText(self._model_cfg("chat").get("provider", "deepseek"))
        model_layout.addRow("对话服务:", self.chat_provider)
        
        self.chat_model = QLineEdit()
        self.chat_model.setMinimumWidth(300)
        self.chat_model.setPlaceholderText("deepseek-v4-flash")
        self.chat_model.setText(self._model_cfg("chat").get("model", ""))
        model_layout.addRow("对话模型:", self.chat_model)
        
        self.chat_url = QLineEdit()
        self.chat_url.setMinimumWidth(300)
        self.chat_url.setPlaceholderText("https://api.deepseek.com (可选)")
        self.chat_url.setText(self._model_cfg("chat").get("base_url", ""))
        model_layout.addRow("API 地址:", self.chat_url)
        
        # 添加分隔
        model_layout.addRow(QLabel(""))
        
        # 复杂模型
        self.complex_provider = QComboBox()
        self.complex_provider.setMinimumWidth(300)
        self.complex_provider.addItems(["deepseek", "openai", "anthropic", "qwen", "custom"])
        self.complex_provider.setCurrentText(self._model_cfg("complex").get("provider", "deepseek"))
        model_layout.addRow("复杂服务:", self.complex_provider)
        
        self.complex_model = QLineEdit()
        self.complex_model.setMinimumWidth(300)
        self.complex_model.setPlaceholderText("deepseek-v4-pro")
        self.complex_model.setText(self._model_cfg("complex").get("model", ""))
        model_layout.addRow("复杂模型:", self.complex_model)
        
        self.complex_url = QLineEdit()
        self.complex_url.setMinimumWidth(300)
        self.complex_url.setPlaceholderText("https://api.deepseek.com (可选)")
        self.complex_url.setText(self._model_cfg("complex").get("base_url", ""))
        model_layout.addRow("API 地址:", self.complex_url)
        
        layout.addWidget(model_group)
        
        # 参数组
        param_group = QGroupBox("参数")
        param_layout = QFormLayout(param_group)
        param_layout.setHorizontalSpacing(15)
        param_layout.setVerticalSpacing(10)
        param_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setMinimumWidth(150)
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setValue(self.current_config.get("llm", {}).get("temperature", 0.7))
        param_layout.addRow("温度:", self.temp_spin)
        
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setMinimumWidth(150)
        self.tokens_spin.setRange(100, 128000)
        self.tokens_spin.setSingleStep(100)
        self.tokens_spin.setValue(self.current_config.get("llm", {}).get("max_tokens", 2048))
        param_layout.addRow("最大 Token:", self.tokens_spin)
        
        layout.addWidget(param_group)
        
        # 测试连接组
        test_group = QGroupBox("测试连接")
        test_layout = QVBoxLayout(test_group)
        test_layout.setContentsMargins(15, 12, 15, 12)
        
        self.test_btn = QPushButton("🔌 测试 LLM 连接")
        self.test_btn.setFixedHeight(36)
        self.test_btn.setMaximumWidth(200)
        self.test_btn.setStyleSheet(
            "background-color: #f0f0f0; color: #333; border: 1px solid #d1d1d6; border-radius: 4px; font-size: 14px;"
        )
        self.test_btn.clicked.connect(self._test_connection)
        test_layout.addWidget(self.test_btn)
        
        self.test_result_label = QLabel("")
        self.test_result_label.setStyleSheet("font-size: 13px; padding: 5px 0;")
        self.test_result_label.setWordWrap(True)
        self.test_result_label.setMinimumHeight(20)
        test_layout.addWidget(self.test_result_label)
        
        layout.addWidget(test_group)
        layout.addStretch()
        
        # 将 tab 放入 scroll
        scroll.setWidget(tab)
        return scroll

    def _create_embedding_tab(self) -> QWidget:
        """创建记忆模型 (Embedding) 配置选项卡"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        # 说明
        hint = QLabel("记忆模型用于将对话内容向量化存储，是记忆检索的基础。")
        hint.setStyleSheet("color: #86868b; font-size: 13px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 模型配置组
        model_group = QGroupBox("模型配置")
        model_layout = QFormLayout(model_group)
        model_layout.setHorizontalSpacing(15)
        model_layout.setVerticalSpacing(10)
        model_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        emb_cfg = self.current_config.get("embedding", {})

        self.emb_model = QLineEdit()
        self.emb_model.setMinimumWidth(300)
        self.emb_model.setPlaceholderText("qwen3.7-text-embedding")
        self.emb_model.setText(emb_cfg.get("model", ""))
        model_layout.addRow("模型名称:", self.emb_model)

        self.emb_url = QLineEdit()
        self.emb_url.setMinimumWidth(300)
        self.emb_url.setPlaceholderText("https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.emb_url.setText(emb_cfg.get("base_url", ""))
        model_layout.addRow("API 地址:", self.emb_url)

        layout.addWidget(model_group)

        # API Key 组
        key_group = QGroupBox("API Key")
        key_layout = QFormLayout(key_group)
        key_layout.setHorizontalSpacing(15)
        key_layout.setVerticalSpacing(10)
        key_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.emb_api_key = QLineEdit()
        self.emb_api_key.setMinimumWidth(300)
        self.emb_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.emb_api_key.setPlaceholderText("输入 Embedding API Key")
        emb_key = emb_cfg.get("api_key", "")
        if emb_key:
            self._original_emb_key = emb_key
            self.emb_api_key.setText(self._mask_api_key(emb_key))
            self.emb_api_key.setPlaceholderText("留空保持不变")
        else:
            self._original_emb_key = ""
        key_layout.addRow("API Key:", self.emb_api_key)

        # 显示/隐藏按钮
        emb_toggle = QPushButton("显示")
        emb_toggle.setCheckable(True)
        emb_toggle.setFixedWidth(60)
        emb_toggle.toggled.connect(self._toggle_emb_key)
        key_layout.addRow("", emb_toggle)

        # 提示：可复用 LLM Key
        reuse_hint = QLabel("如果与对话模型使用同一服务商，可填入相同的 Key。")
        reuse_hint.setStyleSheet("color: #86868b; font-size: 12px;")
        reuse_hint.setWordWrap(True)
        key_layout.addRow("", reuse_hint)

        layout.addWidget(key_group)

        # 测试连接组
        test_group = QGroupBox("测试连接")
        test_layout = QVBoxLayout(test_group)
        test_layout.setContentsMargins(15, 12, 15, 12)

        self.emb_test_btn = QPushButton("🔌 测试 Embedding 连接")
        self.emb_test_btn.setFixedHeight(36)
        self.emb_test_btn.setMaximumWidth(220)
        self.emb_test_btn.setStyleSheet(
            "background-color: #f0f0f0; color: #333; border: 1px solid #d1d1d6; border-radius: 4px; font-size: 14px;"
        )
        self.emb_test_btn.clicked.connect(self._test_embedding_connection)
        test_layout.addWidget(self.emb_test_btn)

        self.emb_test_result = QLabel("")
        self.emb_test_result.setStyleSheet("font-size: 13px; padding: 5px 0;")
        self.emb_test_result.setWordWrap(True)
        self.emb_test_result.setMinimumHeight(20)
        test_layout.addWidget(self.emb_test_result)

        layout.addWidget(test_group)
        layout.addStretch()

        scroll.setWidget(tab)
        return scroll

    def _toggle_emb_key(self, checked: bool):
        """显示/隐藏 Embedding API Key"""
        if checked:
            self.emb_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            if hasattr(self, '_original_emb_key') and self._original_emb_key:
                self.emb_api_key.setText(self._original_emb_key)
            self.sender().setText("隐藏")
        else:
            self.emb_api_key.setEchoMode(QLineEdit.EchoMode.Password)
            if hasattr(self, '_original_emb_key') and self._original_emb_key:
                self.emb_api_key.setText(self._mask_api_key(self._original_emb_key))
            self.sender().setText("显示")

    def _test_embedding_connection(self):
        """测试 Embedding 连接"""
        api_key = self.emb_api_key.text()
        if api_key and hasattr(self, '_original_emb_key') and self._original_emb_key:
            if api_key.endswith(self._original_emb_key[-4:]):
                api_key = self._original_emb_key

        model = self.emb_model.text()
        base_url = self.emb_url.text()

        if not model:
            self.emb_test_result.setText("请先输入模型名称")
            self.emb_test_result.setStyleSheet("color: #dc3545;")
            return
        if not base_url:
            self.emb_test_result.setText("请先输入 API 地址")
            self.emb_test_result.setStyleSheet("color: #dc3545;")
            return
        if not api_key:
            self.emb_test_result.setText("请先输入 API Key")
            self.emb_test_result.setStyleSheet("color: #dc3545;")
            return

        self.emb_test_btn.setEnabled(False)
        self.emb_test_btn.setText("⏳ 测试中...")
        self.emb_test_result.setText("正在连接 Embedding API，请稍候...")
        self.emb_test_result.setStyleSheet("color: #666;")

        self._emb_test_thread = EmbeddingTester(api_key, model, base_url)
        self._emb_test_thread.finished.connect(self._on_emb_test_finished)
        self._emb_test_thread.error.connect(self._on_emb_test_error)
        self._emb_test_thread.start()

    def _on_emb_test_finished(self, dim):
        """Embedding 测试成功"""
        self.emb_test_btn.setEnabled(True)
        self.emb_test_btn.setText("✓ 测试成功")
        self.emb_test_result.setText(f"连接正常！向量维度: {dim}")
        self.emb_test_result.setStyleSheet("color: #28a745;")

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self.emb_test_btn.setText("🔌 测试 Embedding 连接"))

    def _on_emb_test_error(self, error_msg):
        """Embedding 测试失败"""
        self.emb_test_btn.setEnabled(True)
        self.emb_test_btn.setText("✗ 测试失败")
        self.emb_test_result.setText(f"连接失败: {error_msg}")
        self.emb_test_result.setStyleSheet("color: #dc3545;")

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self.emb_test_btn.setText("🔌 测试 Embedding 连接"))

    def _create_appearance_tab(self) -> QWidget:
        """创建外观配置选项卡"""
        # 使用 QScrollArea 包裹内容，避免被挤压
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 显示组
        display_group = QGroupBox("显示")
        display_layout = QFormLayout(display_group)
        display_layout.setHorizontalSpacing(15)
        display_layout.setVerticalSpacing(10)
        display_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setMinimumWidth(150)
        self.opacity_spin.setRange(0.3, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setValue(self.current_config.get("appearance", {}).get("opacity", 1.0))
        display_layout.addRow("窗口透明度:", self.opacity_spin)
        
        layout.addWidget(display_group)
        
        # 窗口行为组
        win_group = QGroupBox("窗口行为")
        win_layout = QVBoxLayout(win_group)
        
        self.always_on_top = QCheckBox("让宠物不被其他窗口遮挡")
        self.always_on_top.setChecked(self.current_config.get("appearance", {}).get("always_on_top", True))
        win_layout.addWidget(self.always_on_top)
        
        layout.addWidget(win_group)
        layout.addStretch()

        # 将 tab 放入 scroll
        scroll.setWidget(tab)
        return scroll

    def _create_behavior_tab(self) -> QWidget:
        """创建行为配置选项卡"""
        # 使用 QScrollArea 包裹内容，避免被挤压
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 自动说话组
        speak_group = QGroupBox("自动说话")
        speak_layout = QFormLayout(speak_group)
        speak_layout.setHorizontalSpacing(15)
        speak_layout.setVerticalSpacing(10)
        speak_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        self.auto_speak = QCheckBox("启用自动说话")
        self.auto_speak.setChecked(self.current_config.get("behavior", {}).get("auto_speak_enabled", True))
        speak_layout.addRow("", self.auto_speak)
        
        self.interval_spin = QSpinBox()
        self.interval_spin.setMinimumWidth(150)
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setSuffix(" 分钟")
        self.interval_spin.setValue(self.current_config.get("behavior", {}).get("auto_speak_interval_min", 5))
        speak_layout.addRow("说话间隔:", self.interval_spin)
        
        layout.addWidget(speak_group)
        
        # 睡眠组
        sleep_group = QGroupBox("睡眠")
        sleep_layout = QFormLayout(sleep_group)
        sleep_layout.setHorizontalSpacing(15)
        sleep_layout.setVerticalSpacing(10)
        sleep_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        self.sleep_spin = QSpinBox()
        self.sleep_spin.setMinimumWidth(150)
        self.sleep_spin.setRange(1, 60)
        self.sleep_spin.setSuffix(" 分钟")
        self.sleep_spin.setValue(self.current_config.get("behavior", {}).get("idle_to_sleep_min", 5))
        sleep_layout.addRow("空闲后睡眠:", self.sleep_spin)
        
        self.sleep_duration = QSpinBox()
        self.sleep_duration.setMinimumWidth(150)
        self.sleep_duration.setRange(1, 30)
        self.sleep_duration.setSuffix(" 分钟")
        self.sleep_duration.setValue(self.current_config.get("behavior", {}).get("sleep_duration_min", 1))
        sleep_layout.addRow("睡眠时长:", self.sleep_duration)
        
        layout.addWidget(sleep_group)
        layout.addStretch()

        # 将 tab 放入 scroll
        scroll.setWidget(tab)
        return scroll

    def _model_cfg(self, task: str) -> dict:
        return self.current_config.get("llm", {}).get("models", {}).get(task, {})

    def _mask_api_key(self, api_key: str) -> str:
        """遮蔽 API Key，只显示前4后4位"""
        if not api_key or len(api_key) <= 8:
            return "****"
        return f"{api_key[:4]}****{api_key[-4:]}"

    def _toggle_api_key(self, checked: bool):
        if checked:
            # 显示完整 Key
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            if self.has_api_key and hasattr(self, '_original_api_key'):
                self.api_key_input.setText(self._original_api_key)
            self.sender().setText("隐藏")
        else:
            # 恢复遮蔽显示
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            if self.has_api_key and hasattr(self, '_original_api_key'):
                self.api_key_input.setText(self._mask_api_key(self._original_api_key))
            self.sender().setText("显示")

    def _save_settings(self):
        try:
            # 保存 API Key
            api_key = self.api_key_input.text()
            # 如果输入不是遮蔽格式，说明用户修改了
            if api_key and not api_key.endswith("****" + (self._original_api_key[-4:] if self.has_api_key else "")):
                self.secure_storage.save_api_key(api_key)
                # 同步更新 config_manager 内部状态
                self.config_manager._config.setdefault("llm", {})["api_key"] = api_key
            elif api_key == "" and self.has_api_key:
                # 用户清空了输入框，删除 API Key
                self.secure_storage.delete_api_key()
                # 同步清空 config_manager 内部状态，防止 save() 又存回旧 key
                self.config_manager._config.setdefault("llm", {})["api_key"] = ""

            # 保存 Embedding API Key
            emb_key = self.emb_api_key.text()
            if emb_key and hasattr(self, '_original_emb_key'):
                if not emb_key.endswith("****") and emb_key != self._mask_api_key(self._original_emb_key):
                    self.secure_storage.save_secret("embedding_api_key", emb_key)
                    self.config_manager._config.setdefault("embedding", {})["api_key"] = emb_key
            elif emb_key and not hasattr(self, '_original_emb_key'):
                self.secure_storage.save_secret("embedding_api_key", emb_key)
                self.config_manager._config.setdefault("embedding", {})["api_key"] = emb_key
            elif not emb_key and self._original_emb_key:
                self.secure_storage.delete_secret("embedding_api_key")
                self.config_manager._config.setdefault("embedding", {})["api_key"] = ""
            
            # 准备更新数据
            updates = {
                "llm": {
                    "temperature": self.temp_spin.value(),
                    "max_tokens": self.tokens_spin.value(),
                    "models": {
                        "chat": {
                            "provider": self.chat_provider.currentText(),
                            "model": self.chat_model.text(),
                            "base_url": self.chat_url.text(),
                        },
                        "complex": {
                            "provider": self.complex_provider.currentText(),
                            "model": self.complex_model.text(),
                            "base_url": self.complex_url.text(),
                        },
                    },
                },
                "embedding": {
                    "model": self.emb_model.text(),
                    "base_url": self.emb_url.text(),
                    "api_key": "",
                },
                "appearance": {
                    "opacity": self.opacity_spin.value(),
                    "always_on_top": self.always_on_top.isChecked(),
                },
                "behavior": {
                    "auto_speak_enabled": self.auto_speak.isChecked(),
                    "auto_speak_interval_min": self.interval_spin.value(),
                    "idle_to_sleep_min": self.sleep_spin.value(),
                    "sleep_duration_min": self.sleep_duration.value(),
                },
            }
            
            # 使用 update 方法保存配置
            self.config_manager.update(updates)
            
            # 重置 LLM 缓存
            try:
                from providers.llm import LLMProvider
                LLMProvider.reset()
            except Exception:
                pass
            
            # 显示成功提示，然后关闭窗口
            self.status_label.setText("✓ 设置已保存")
            self.status_label.setStyleSheet("color: #28a745;")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(800, self.accept)
            
        except Exception as e:
            logger.error(f"[Settings] Save failed: {e}")
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"✗ 保存失败: {str(e)}")
            self.status_label.setStyleSheet("color: #dc3545;")

    def _test_connection(self):
        """测试 LLM 连接"""
        # 获取 API key
        api_key = self.api_key_input.text()
        # 如果是遮蔽格式，使用原始 key
        if api_key and self.has_api_key and api_key.endswith(self._original_api_key[-4:]):
            api_key = self._original_api_key

        # 获取当前配置（使用界面上的值）
        model_config = {
            "model": self.chat_model.text(),
            "base_url": self.chat_url.text(),
            "provider": self.chat_provider.currentText(),
        }

        # 显示测试中
        self.test_btn.setEnabled(False)
        self.test_btn.setText("⏳ 测试中...")
        self.test_result_label.setText("正在连接 LLM，请稍候...")
        self.test_result_label.setStyleSheet("color: #666;")

        # 创建并启动测试线程
        self._test_thread = LLMTester(api_key, model_config)
        self._test_thread.finished.connect(self._on_test_finished)
        self._test_thread.error.connect(self._on_test_error)
        self._test_thread.start()

    def _on_test_finished(self, response_text):
        """测试成功回调"""
        self.test_btn.setEnabled(True)
        self.test_btn.setText("✓ 测试成功")
        self.test_result_label.setText(f"连接正常！模型返回: \"{response_text[:20]}...\"")
        self.test_result_label.setStyleSheet("color: #28a745;")
        
        # 2秒后恢复按钮文字
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self.test_btn.setText("🔌 测试 LLM 连接"))

    def _on_test_error(self, error_msg):
        """测试失败回调"""
        self.test_btn.setEnabled(True)
        self.test_btn.setText("✗ 测试失败")
        self.test_result_label.setText(f"连接失败: {error_msg}")
        self.test_result_label.setStyleSheet("color: #dc3545;")
        
        # 2秒后恢复按钮文字
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self.test_btn.setText("🔌 测试 LLM 连接"))


class LLMTester(QThread):
    """异步测试 LLM 连接的线程"""
    finished = pyqtSignal(str)  # 成功信号
    error = pyqtSignal(str)     # 失败信号

    def __init__(self, api_key: str, model_config: dict):
        super().__init__()
        self.api_key = api_key
        self.model_config = model_config

    def run(self):
        try:
            # 获取配置
            model_name = self.model_config.get("model", "")
            base_url = self.model_config.get("base_url", "")
            provider = self.model_config.get("provider", "deepseek")

            if not model_name:
                self.error.emit("请先配置模型名称")
                return

            if not self.api_key:
                self.error.emit("请先输入 API Key")
                return

            # 使用 langchain 的 init_chat_model 直接创建 LLM
            from langchain.chat_models import init_chat_model
            
            provider_map = {
                "deepseek": "openai",
                "openai": "openai",
                "qwen": "openai",
                "custom": "openai",
            }
            actual_provider = provider_map.get(provider, "openai")

            kwargs = {
                "model": model_name,
                "model_provider": actual_provider,
                "api_key": self.api_key,
                "temperature": 0.1,
            }
            if base_url:
                kwargs["base_url"] = base_url

            llm = init_chat_model(**kwargs)

            # 创建事件循环运行异步调用
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                response = loop.run_until_complete(
                    llm.ainvoke("你好，请回复四个字：连接成功")
                )
                response_text = response.content if hasattr(response, 'content') else str(response)
                self.finished.emit(response_text)
            finally:
                loop.close()

        except Exception as e:
            error_msg = str(e)
            # 简化错误信息
            if "Authentication" in error_msg or "401" in error_msg:
                error_msg = "API Key 无效，请检查是否正确"
            elif "Connection" in error_msg or "timeout" in error_msg.lower():
                error_msg = "网络连接失败，请检查网络或 API 地址"
            elif "not found" in error_msg.lower() or "404" in error_msg:
                error_msg = "模型不存在，请检查模型名称"

            logger.error(f"[Settings] LLM test failed: {e}")
            self.error.emit(error_msg)


class EmbeddingTester(QThread):
    """异步测试 Embedding 连接的线程"""
    finished = pyqtSignal(int)   # 成功信号，返回向量维度
    error = pyqtSignal(str)      # 失败信号

    def __init__(self, api_key: str, model: str, base_url: str):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def run(self):
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

            response = client.embeddings.create(
                model=self.model,
                input="测试连接",
            )

            if response.data and len(response.data) > 0:
                dim = len(response.data[0].embedding)
                self.finished.emit(dim)
            else:
                self.error.emit("API 返回空数据")
        except Exception as e:
            error_msg = str(e)
            if "Authentication" in error_msg or "401" in error_msg:
                error_msg = "API Key 无效，请检查是否正确"
            elif "Connection" in error_msg or "timeout" in error_msg.lower():
                error_msg = "网络连接失败，请检查网络或 API 地址"
            elif "not found" in error_msg.lower() or "404" in error_msg:
                error_msg = "模型不存在，请检查模型名称"

            logger.error(f"[Settings] Embedding test failed: {e}")
            self.error.emit(error_msg)
