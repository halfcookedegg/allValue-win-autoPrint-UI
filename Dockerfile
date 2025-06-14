# Dockerfile (最终生产版 - 多阶段构建)

# --- 阶段 1: 构建器 (Builder) ---
# 这个阶段包含了所有编译工具，它的唯一任务是安装好所有的Python库。
FROM python:3.11-slim as builder

# 安装编译Python库（如reportlab）所需的系统依赖
# - build-essential: 包含了gcc等基础编译工具链
# - libfreetype-dev: 包含了编译reportlab所需的freetype字体库开发文件
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libfreetype-dev \
    && rm -rf /var/lib/apt/lists/*

# 创建一个虚拟环境，这是在容器中管理依赖的最佳实践
# 这样可以保持全局Python环境的干净
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 复制依赖清单文件到构建器中
COPY requirements.txt .

# 使用虚拟环境中的pip安装所有Python库
# --no-cache-dir 选项可以减小镜像体积
RUN pip install --no-cache-dir -r requirements.txt


# --- 阶段 2: 最终运行环境 (Final Stage) ---
# 我们再次从一个干净的、非常小的slim镜像开始
FROM python:3.11-slim

# 设置环境变量，防止Python生成.pyc文件，并启用非缓冲模式以实时查看日志
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 只安装运行你的应用所必需的底层库
# - cups-client: 提供 lp 和 lpstat 命令，用于打印
# - fonts-noto-cjk: 提供高质量的Noto中日韩字体，确保PDF中的中文能正确渲染
# - libfreetype6: 运行reportlab所需的非开发版freetype库
RUN apt-get update && apt-get install -y --no-install-recommends \
    cups-client \
    fonts-noto-cjk \
    libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

# 在最终镜像中创建工作目录
WORKDIR /app

# 关键一步：从'builder'阶段，只复制已经安装好的Python库（虚拟环境）过来。
# 我们没有复制build-essential等编译工具，所以最终镜像会非常小！
COPY --from=builder /opt/venv /opt/venv

# 将虚拟环境的路径加入到PATH中，这样系统就能找到我们安装的库（如gunicorn）
ENV PATH="/opt/venv/bin:$PATH"

# 复制你的所有应用代码到容器中
COPY . .

# 暴露Flask应用对外提供服务的端口
EXPOSE 5000

# (可选，但推荐) 添加健康检查
# 这会告诉Docker如何检查我们的应用是否还在健康运行
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -f http://localhost:5000/ || exit 1

# 定义容器启动时运行的最终命令
# 我们使用 Gunicorn 这个生产级别的WSGI服务器来运行你的Flask应用
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:5000", "app:app"]
