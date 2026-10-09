# Snap2Map 北京版（ChatGPT 粘贴版）

无需 OpenAI API Key。把截图发给 ChatGPT，要求按每行「名称 TAB 地址 TAB 预约状态」输出，复制到网页输入框即可。高德 API Key 仍用于定位和路线查询。

## Mac 启动

1. 解压 ZIP，确认文件夹内有 `beijing_app_chatgpt.py` 和 `requirements.txt`。
2. 在终端进入该文件夹，例如：`cd ~/Downloads/snap2map_chatgpt_beijing`。
3. 首次安装：`python3 -m venv .venv`、`source .venv/bin/activate`、`python -m pip install -r requirements.txt`。
4. 启动：`python -m streamlit run beijing_app_chatgpt.py`。
5. 打开 http://localhost:8501 。停止运行按 Ctrl+C。

## 注意

- 本版不会自动读取截图，截图先交给 ChatGPT 识别。
- 复制每行三列，以 Tab 或 | 分隔；也支持只写地点名称（精度较低）。
- 高德的定位结果可能匹配到同名地点、道路或区域，务必检查。
- 通勤时长是 API 估算值，非实时到达保证。
- HTML 地图底图在线加载，需要网络。
