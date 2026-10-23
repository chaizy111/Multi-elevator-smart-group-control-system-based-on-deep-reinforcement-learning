# 本地API

启动：`python -m elevator_control.cli serve --host 127.0.0.1 --port 8000`。生产网页同源在8000；交互式完整OpenAPI在`http://127.0.0.1:8000/docs`。

REST前缀`/api/v1`：health、config/defaults、config/validate、traces、simulations、experiments、models、training-runs。仿真子资源为snapshot、metrics、passengers、artifacts、commands；乘客按offset/limit/floor/status分页。模型和训练来自真实注册与日志目录。

`GET /simulations/{id}/timeseries?limit=500`从真实归档CSV返回`{available,total,items:[{time,wait}]}`；limit为2–1000，等间隔抽样保留真实首尾，空等待均值为null。未归档时available=false。两遍流式读取限制内存；页面终态仅补查一次，最快模式也能展示完整时间范围的真实趋势。

```json
{"config":{"building":{"floor_count":12,"elevator_count":4,"capacity":12}},"controller":{"name":"eta"},"speed_multiplier":5}
```

POST simulations得到CREATED，再POST `/simulations/{id}/commands`：

```json
{"command_id":"client-unique-id","type":"start","payload":{}}
```

命令为start/pause/resume/reset/stop/speed。相同command_id及payload只执行一次，不同payload重用ID返回409。Pause接受后等状态PAUSED确认，Resume不重置。Reset保留旧产物，返回新CREATED run_id。speed为0（最快）/1/5/20，只影响墙钟。

WebSocket `/ws/v1/simulations/{id}`推送完整快照、command_applied、status_changed、completed/error和heartbeat，sequence去旧，连接断开不停止作业。最终结果经REST补查。图片、报告及原始CSV通过已登记artifact ID下载，不能传任意文件路径。

错误结构含code/message/details/request_id。非法字段422、未知ID404、状态冲突409、资源额度429；worker失败可查failure.json。仅单API协调器，勿启多个Uvicorn workers。
