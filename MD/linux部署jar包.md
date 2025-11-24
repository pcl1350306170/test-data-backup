在Linux系统中，对于测试的jar包，通常可以将其放在 `/usr/local/` 下自己创建的专门目录（比如 `/usr/local/apps`），这样便于管理。

### 步骤1：创建目录（若需）
如果没有合适的目录，可以先创建：
```bash
sudo mkdir -p /usr/local/apps/base-service
sudo mv base-service-3.0.0-SNAPSHOT.jar /usr/local/apps/base-service/
```

### 步骤2：后台执行命令
使用 `nohup` 命令让其在后台执行，同时将日志输出到指定文件（避免日志丢失）：
```bash
cd /usr/local/apps/base-service
nohup java -jar base-service-3.0.0-SNAPSHOT.jar > base-service.log 2>&1 &
```
- `nohup`：忽略挂起信号，保证退出终端后程序仍运行。
- `java -jar`：执行jar包的标准命令。
- `> base-service.log 2>&1`：将标准输出和错误输出都重定向到 `base-service.log` 文件。
- `&`：将进程放入后台运行。

执行后，可通过 `ps -ef | grep base-service` 查看进程是否正常运行，通过 `tail -f base-service.log` 查看日志输出。