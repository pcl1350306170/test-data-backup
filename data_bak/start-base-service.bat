@echo off
REM 设置JAR路径
set JAR_PATH=D:\CODE\Java\my-blog-api\target\base-service-3.0.0-SNAPSHOT.jar

REM 启动服务，后台运行
start /b "" java -jar "%JAR_PATH%"
