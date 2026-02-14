# Happy Lad v2

重构版：多摄像头统一管理 + 低延迟预览（MJPEG）+ 更清晰的采样策略。

## 功能
- 多摄像头统一管理页面
- 摄像头详情页（实时预览、最新抓拍）
- 可配置采样规则：观察年限/冷却时间/房间名称
- 事件采样：检测到人时以概率保存图片

## 目录结构
```
happy_lad_v2/
  app/
    main.py                # 入口
    config.py              # 配置加载
    routes/                # Flask 路由
    services/              # 推理管线/采样/存储
    templates/             # 页面模板
    static/                # CSS/JS
  configs/cameras.yaml     # 摄像头配置
  scripts/run.sh           # 启动脚本
  systemd/happy_lad_v2.service
  requirements.txt
```

## 启动
```bash
pip install -r requirements.txt
python3 -m app.main --config configs/cameras.yaml --host 0.0.0.0 --port 5000
```

## systemd
```bash
sudo cp systemd/happy_lad_v2.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart happy_lad_v2.service
sudo journalctl -u happy_lad_v2.service -f
```
