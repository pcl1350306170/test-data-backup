@echo off
REM 设置JAR路径
set JAR_PATH=D:\CODE\Java\Geeker-Admin-Java\target\geekeradmin-0.0.1-SNAPSHOT.jar

REM 启动服务，后台运行
start /b "" java -jar "%JAR_PATH%"
