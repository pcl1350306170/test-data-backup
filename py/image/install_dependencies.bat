@echo off
chcp 65001 >nul
echo ========================================
echo  图片放大增强工具 - 依赖安装脚本
echo  (适配 Python 3.13+ / 新版 setuptools)
echo ========================================
echo.

echo [1/8] 安装基础依赖...
pip install opencv-python numpy tqdm wheel -i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo [2/8] 安装 PyTorch（CPU 版本）...
pip install torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo [3/8] 临时降级 setuptools（basicsr 构建需要）...
pip install "setuptools<70"

echo.
echo [4/8] 下载并修补 basicsr 源码（修复 Python 3.13+ locals() 兼容性）...
python -c "import urllib.request,tarfile,os;urllib.request.urlretrieve('https://pypi.tuna.tsinghua.edu.cn/packages/86/41/00a6b000f222f0fa4c6d9e1d6dcc9811a374cabb8abb9d408b77de39648c/basicsr-1.4.2.tar.gz','C:/temp/basicsr-1.4.2.tar.gz');tarfile.open('C:/temp/basicsr-1.4.2.tar.gz').extractall('C:/temp/basicsr_src');print('Downloaded and extracted')"
python -c "f=r'C:\temp\basicsr_src\basicsr-1.4.2\setup.py';c=open(f,'r').read();c=c.replace('exec(compile(f.read(), version_file, \'exec\'))\n    return locals()[\'__version__\']','version_ns = {}\n        exec(compile(f.read(), version_file, \'exec\'), version_ns)\n    return version_ns[\'__version__\']');open(f,'w').write(c);print('setup.py patched')"

echo.
echo [5/8] 从修补后的源码安装 basicsr...
cd C:\temp\basicsr_src\basicsr-1.4.2
pip install . --no-build-isolation --no-deps
cd %~dp0

echo.
echo [6/8] 恢复 setuptools 并安装主包...
pip install --upgrade setuptools -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install realesrgan facexlib gfpgan --no-deps -i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo [7/8] 安装子依赖...
pip install addict future lmdb filterpy yapf -i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo [8/8] 修补 basicsr 兼容新版 torchvision...
python -c "f=r'D:\dev\python\Lib\site-packages\basicsr\data\degradations.py';c=open(f,'r',encoding='utf-8').read();c=c.replace('from torchvision.transforms.functional_tensor import rgb_to_grayscale','try:\n    from torchvision.transforms.functional import rgb_to_grayscale\nexcept ImportError:\n    from torchvision.transforms.functional_tensor import rgb_to_grayscale');open(f,'w',encoding='utf-8').write(c);print('degradations.py patched')"

echo.
echo ========================================
echo  验证安装...
echo ========================================
python -c "import realesrgan; print('Real-ESRGAN OK')" 2>nul && echo ✅ Real-ESRGAN 安装成功 || echo ❌ Real-ESRGAN 安装失败
python -c "import gfpgan; print('GFPGAN OK')" 2>nul && echo ✅ GFPGAN 安装成功 || echo ❌ GFPGAN 安装失败
python -c "import basicsr; print('BasicSR OK')" 2>nul && echo ✅ BasicSR 安装成功 || echo ❌ BasicSR 安装失败

echo.
echo ========================================
echo  安装完成！
echo ========================================
echo.
echo 首次运行会自动下载模型文件（约 300MB）
echo 模型会保存到 weights/ 目录
echo.
echo 运行程序: python image_enhancer.pyw
echo.
pause
