## auto_update.py
## 自动更新模块
## 包含检查更新、下载更新、智能同步文件等功能
import os
import re
import shutil
import sys
import tempfile
import zipfile
import datetime
import urllib.request


def get_xpi_info_from_repo(owner, repo, branch='main', expected_version=None, update_source='github'):
    """
    根据已知的命名规则直接构造 Zotero PDF 2 ZH 插件的下载链接。
    命名规则：zotero-pdf-2-zh-v{expected_version}.xpi

    Args:
        owner: 仓库所有者
        repo: 仓库名称
        branch: 分支名称，默认为 'main'
        expected_version: 期望的版本号
        update_source: 更新源，'github' 或 'gitee'

    Returns:
        (download_url, target_filename): 下载链接和文件名，失败时返回 (None, None)
    """
    if not expected_version:
        print("  - ⚠️ 未提供版本号，无法构造插件下载链接。")
        return None, None
    try:
        # 构造文件名
        target_filename = f"zotero-pdf-2-zh-v{expected_version}.xpi"
        # 构造 GitHub raw 文件下载链接
        if update_source == 'github':
            download_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{target_filename}"
        else: # gitee
            download_url = f"https://gitee.com/{owner}/{repo}/raw/{branch}/{target_filename}"
        print(f"  - 构造插件下载链接: {download_url}")
        # 可选：验证链接是否有效
        with urllib.request.urlopen(download_url, timeout=1000) as response:
            if response.status == 200:
                print(f"  - 成功验证插件: {target_filename}")
                return download_url, target_filename
            else:
                print(f"  - ⚠️ 无法访问插件文件，状态码: {response.status}")
                return None, None
    except Exception as e:
        print(f"  - ⚠️ 无法获取插件文件 (可能是网络问题或文件不存在): {e}")
        return None, None


def smart_file_sync(source_dir, target_dir, stats, backup_dir, updated_files, new_files, exclude_dirs=None):
    """
    智能文件同步：比较文件内容，只更新真正改变的文件。同时备份受影响的文件，并跟踪更新和新增。

    Args:
        source_dir: 新版本的文件夹路径
        target_dir: 目标文件夹路径
        stats: 统计信息字典 {'updated': 0, 'new': 0, 'preserved': 0, 'unchanged': 0}
        backup_dir: 备份目录，用于存储将被更新的文件的备份
        updated_files: 列表，用于跟踪更新的文件相对路径
        new_files: 列表，用于跟踪新增的文件相对路径
        exclude_dirs (list, optional): 需要完全跳过的目录名列表。 Defaults to None.
    """
    if exclude_dirs is None:
        exclude_dirs = []

    for root, dirs, files in os.walk(source_dir):
        # 优化点 1: 在遍历时，从 dirs 列表中移除需要排除的目录
        # 这样 os.walk 就不会进入这些目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        # 计算相对路径
        rel_dir = os.path.relpath(root, source_dir)
        target_root = os.path.join(target_dir, rel_dir) if rel_dir != '.' else target_dir

        # 确保目标目录存在
        os.makedirs(target_root, exist_ok=True)

        # 同步文件
        for file in files:
            source_file = os.path.join(root, file)
            target_file = os.path.join(target_root, file)
            rel_file_path = os.path.join(rel_dir, file) if rel_dir != '.' else file

            if os.path.exists(target_file): # 比较文件内容
                try:
                    with open(source_file, 'rb') as sf, open(target_file, 'rb') as tf:
                        source_content = sf.read()
                        target_content = tf.read()

                    if source_content != target_content:
                        # 文件内容不同，需要更新：先备份原文件
                        backup_file = os.path.join(backup_dir, rel_file_path)
                        os.makedirs(os.path.dirname(backup_file), exist_ok=True)
                        shutil.copy2(target_file, backup_file)
                        # 更新
                        shutil.copy2(source_file, target_file)
                        print(f"    ✓ 更新: {rel_file_path}")
                        stats['updated'] += 1
                        updated_files.append(rel_file_path)
                    else:
                        # 文件内容相同，无需更新
                        print(f"    ≡ 跳过: {rel_file_path} (内容相同)")
                        stats['unchanged'] += 1
                except Exception as e:
                    # 比较出错时，保守地更新文件：先备份
                    backup_file = os.path.join(backup_dir, rel_file_path)
                    os.makedirs(os.path.dirname(backup_file), exist_ok=True)
                    shutil.copy2(target_file, backup_file)
                    shutil.copy2(source_file, target_file)
                    print(f"    ⚠️ 比较失败，强制更新: {rel_file_path} ({e})")
                    stats['updated'] += 1
                    updated_files.append(rel_file_path)
            else:
                # 新文件
                shutil.copy2(source_file, target_file)
                print(f"    + 新增: {rel_file_path}")
                stats['new'] += 1
                new_files.append(rel_file_path)


def count_preserved_files(source_dir, target_dir, stats, exclude_dirs=None):
    """
    统计保留的用户文件（在target中存在但source中不存在的文件）

    Args:
        source_dir: 新版本的文件夹路径
        target_dir: 目标文件夹路径
        stats: 统计信息字典 {'updated': 0, 'new': 0, 'preserved': 0, 'unchanged': 0}
        exclude_dirs (list, optional): 需要完全跳过的目录名列表。 Defaults to None.
    """
    if exclude_dirs is None:
        exclude_dirs = []

    for root, dirs, files in os.walk(target_dir):
        # 优化点 2: 同样地，在统计保留文件时也跳过排除目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        rel_dir = os.path.relpath(root, target_dir)
        source_root = os.path.join(source_dir, rel_dir) if rel_dir != '.' else source_dir

        for file in files:
            source_file = os.path.join(source_root, file)
            if not os.path.exists(source_file):
                rel_file_path = os.path.join(rel_dir, file) if rel_dir != '.' else file
                print(f"    ◆ 保留: {rel_file_path} (用户文件)")
                stats['preserved'] += 1


def perform_update_optimized(root_path, local_version, expected_version=None, update_source='github'):
    """
    优化的更新逻辑：结合智能同步和临时目录的优点，使用针对性备份避免操作无关目录（如虚拟环境）。

    Args:
        root_path: 当前服务端目录路径
        local_version: 当前本地版本号
        expected_version: 期望的版本号（可选）
        update_source: 更新源，'github' 或 'gitee'
    """
    print("🚀 [自动更新] 开始更新 (智能同步模式)...请稍候。")
    owner, repo = 'osoulmate', 'zotero-pdf2zh'
    project_root = os.path.dirname(root_path)
    print(f"   - 项目根目录: {project_root}")
    print(f"   - 当前服务目录: {root_path}")

    # 优化点 3: 定义一个排除列表，包含虚拟环境和常见的缓存目录
    # 这是保护虚拟环境的关键
    EXCLUDE_DIRECTORIES = ['zotero-pdf2zh-next-venv', 'zotero-pdf2zh-venv']
    print(f"   - 🛡️ 更新将自动忽略以下目录: {EXCLUDE_DIRECTORIES}")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(project_root, f"server_backup_{timestamp}")
    os.makedirs(backup_path, exist_ok=True)

    zip_filename = f"server_{expected_version or 'latest'}.zip"
    server_zip_path = os.path.join(project_root, zip_filename)

    stats = {'updated': 0, 'new': 0, 'preserved': 0, 'unchanged': 0}
    updated_files = []
    new_files = []

    try:
        # --- 步骤 1: 下载文件 ---
        xpi_url, xpi_filename = get_xpi_info_from_repo(owner, repo, 'main', expected_version, update_source=update_source)
        if xpi_url and xpi_filename:
            xpi_save_path = os.path.join(project_root, xpi_filename)
            print(f"  - 正在下载插件文件 ({xpi_filename})...")
            if os.path.exists(xpi_save_path):
                os.remove(xpi_save_path)
            urllib.request.urlretrieve(xpi_url, xpi_save_path)
            print("  - ✅ 插件文件下载完成, 请将新版本插件安装到Zotero中")
        else:
            print("  - ⚠️ 未找到合适的插件文件，跳过插件下载。")

        if update_source == 'gitee':
            server_zip_url = f"https://gitee.com/{owner}/{repo}/raw/main/server.zip"
        else:
            server_zip_url = f"https://github.com/{owner}/{repo}/raw/main/server.zip"
        print(f"  - 正在下载服务端文件 ({zip_filename})...")
        urllib.request.urlretrieve(server_zip_url, server_zip_path)
        print("  - ✅ 服务端文件下载完成")

        # --- 步骤 2: 使用临时目录解压并智能同步 ---
        print("  - 正在解压并同步新版本...")
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(server_zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            new_server_path = os.path.join(temp_dir, 'server')
            if not os.path.exists(new_server_path):
                new_server_path = temp_dir

            print("    - 开始智能文件同步:")
            # 优化点 4: 将排除列表传递给同步函数
            smart_file_sync(new_server_path, root_path, stats, backup_path, updated_files, new_files, exclude_dirs=EXCLUDE_DIRECTORIES)
            # 优化点 5: 将排除列表传递给统计函数
            count_preserved_files(new_server_path, root_path, stats, exclude_dirs=EXCLUDE_DIRECTORIES)

        # --- 步骤 3 & 4 & 回滚逻辑: (这部分代码无需改动，保持原样) ---
        print(f"\n📊 同步统计报告:")
        print(f"    - 📝 更新的文件: {stats['updated']}")
        print(f"    - ➕ 新增的文件: {stats['new']}")
        print(f"    - ◆ 保留的文件: {stats['preserved']}")
        print(f"    - ≡ 跳过的文件: {stats['unchanged']} (内容相同)")
        print(f"    - 📁 总处理文件: {sum(stats.values())}")

        print("  - 正在清理临时文件...")
        if os.path.exists(backup_path):
            shutil.rmtree(backup_path)
        os.remove(server_zip_path)
        print("  - ✅ 清理完成")

        print(f"\n✅ 更新成功！")
        if xpi_filename:
            print(f"   - 📦 最新的插件文件 '{xpi_filename}' 已下载到项目主目录")
            print("   - 🔄 请将插件文件重新安装到Zotero中")
        print("   - 🚀 请重新启动 server.py 脚本以应用新版本")
        print("   - 🛡️ 您的配置文件和虚拟环境已安全保留")

    except Exception as e:
        print(f"\n❌ 更新失败: {e}")
        print("  - 正在尝试从备份回滚...")
        try:
            for rel_path in updated_files:
                backup_file = os.path.join(backup_path, rel_path)
                target_file = os.path.join(root_path, rel_path)
                if os.path.exists(backup_file):
                    shutil.copy2(backup_file, target_file)
                    print(f"    - 回滚更新: {rel_path}")

            for rel_path in new_files:
                target_file = os.path.join(root_path, rel_path)
                if os.path.exists(target_file):
                    os.remove(target_file)
                    print(f"    - 回滚新增: {rel_path}")

            print("  - ✅ [自动更新] 已成功回滚到更新前的状态")
        except Exception as rollback_error:
            print(f"  - ❌ [自动更新] 回滚失败: {rollback_error}")
            print(f"  - 💾 [自动更新] 备份文件保留在: {backup_path}")

    finally:
        if os.path.exists(server_zip_path):
            os.remove(server_zip_path)
        sys.exit()


def check_for_updates(local_version, update_source='github'):
    """
    从 GitHub 检查是否有新版本。

    Args:
        local_version: 当前本地版本号
        update_source: 更新源，'github' 或 'gitee'

    Returns:
        如果存在新版本，返回 (local_version, remote_version)，否则返回 None。
    """
    print("🔍 [自动更新] 正在检查更新...")
    if update_source == 'gitee':
        remote_script_url = "https://gitee.com/osoulmate/zotero-pdf2zh/raw/main/server/server.py"
    else:
        remote_script_url = "https://raw.githubusercontent.com/osoulmate/zotero-pdf2zh/main/server/server.py"
    try:
        with urllib.request.urlopen(remote_script_url, timeout=30) as response:
            remote_content = response.read().decode('utf-8')
        match = re.search(r'__version__\s*=\s*["\'](.+?)["\']', remote_content)
        if not match:
            print("⚠️ [自动更新] 无法在远程文件中找到版本信息, 已跳过.\n")
            return None
        remote_version = match.group(1)
        if tuple(map(int, remote_version.split('.'))) > tuple(map(int, local_version.split('.'))):
            return local_version, remote_version
        else:
            print("✅ [自动更新] 您的程序已是最新版本.\n")
            return None
    except Exception as e:
        print(f"⚠️ [自动更新] 检查更新失败 (可能是网络问题)，已跳过。错误: {e}\n")
        return None
