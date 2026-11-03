@echo off
chcp 65001 >nul
title 推送项目到 GitHub

echo ==============================================================
echo       🚀 AI-Credits-Hub 一键推送到 GitHub
echo ==============================================================
echo.
echo 提示：请先在 GitHub (https://github.com/new) 新建一个仓库
echo 仓库名称建议填: AI-Credits-Hub (选择 Public 或 Private 均可，不要勾选添加 README)
echo.

set /p REPO_URL="请输入你的 GitHub 仓库地址 (例如 https://github.com/bishuyuan/AI-Credits-Hub.git): "

if "%REPO_URL%"=="" (
    echo [错误] 仓库地址不能为空！
    pause
    exit /b 1
)

git remote remove origin >nul 2>&1
git remote add origin %REPO_URL%
git branch -M main

echo.
echo 正在推送到 GitHub...
git push -u origin main

if %ERRORLEVEL% equ 0 (
    echo.
    echo ==============================================================
    echo  🎉 恭喜！项目已成功推送到你的 GitHub！
    echo ==============================================================
) else (
    echo.
    echo [提示] 推送遇到问题，请检查网络（或梯子），或确认 GitHub 登录凭证。
)

echo.
pause
