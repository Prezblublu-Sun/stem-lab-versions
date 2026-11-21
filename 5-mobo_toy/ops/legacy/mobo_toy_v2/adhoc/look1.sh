#!/usr/bin/env bash
find ~/mobo_toy_v2 ~/ml3406 -name 'pool_area_features*' -not -path '*/.venv/*' 2>/dev/null | head
find ~/mobo_toy_v2/code -maxdepth 2 -name '*.py' -newermt '2026-10-25' | head -n 30
echo "--- processes of this user, parents"
ps -u "$USER" -o pid,ppid,etime,cmd --sort=ppid | grep -vE 'sshd|ps -u|grep|look1' | cut -c1-120 | head -n 40
echo "--- loads"
uptime; nproc; free -g | head -n 2; df -BG --output=avail / | tail -1
