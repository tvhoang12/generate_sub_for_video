#!/usr/bin/env bash
# Kiểm tra toàn diện dung lượng ổ đĩa cho substudio — CHỈ ĐỌC, không xóa/sửa/dừng gì.
# Chạy:  sudo bash check_disk.sh
# Kết quả in ra màn hình và lưu vào REPORT_DIR (mặc định trên lv_hls vì ổ / có thể đã đầy).

set -u
PROJECT_DIR="${PROJECT_DIR:-/home/vtechdev/substudio}"
CONTAINER="${CONTAINER:-substudio}"
REPORT_DIR="${REPORT_DIR:-/var/www/hls/substudio}"
REPORT="$REPORT_DIR/disk-report-$(date +%Y%m%d-%H%M%S).txt"
DU_TIMEOUT=600

if [ "$(id -u)" -ne 0 ]; then
  echo "Hãy chạy bằng sudo: sudo bash $0"; exit 1
fi

exec > >(tee "$REPORT") 2>&1

sec() { printf '\n==================== %s ====================\n' "$*"; }
run() { printf '\n$ %s\n' "$*"; timeout "$DU_TIMEOUT" bash -c "$*" 2>&1; }
# du trong phạm vi ổ / (-x: không đi sang ổ khác như /var/www/hls)
dux() { printf '\n$ du -xh --max-depth=%s %s\n' "$2" "$1"; timeout "$DU_TIMEOUT" du -xh --max-depth="$2" "$1" 2>/dev/null | sort -rh | head -"${3:-20}"; }

sec "0. THÔNG TIN CHUNG"
run "date; hostname; uptime"

sec "1. DUNG LƯỢNG & INODE"
run "df -hT -x tmpfs -x devtmpfs"
run "df -i -x tmpfs -x devtmpfs"

sec "2. THƯ MỤC LỚN TRÊN Ổ / (không tính /var/www/hls)"
dux / 1 25
dux /var 1
dux /var/lib 1
dux /home 2 25
dux /root 2
dux /tmp 2
dux /opt 2
dux /srv 2

sec "3. DỰ ÁN SUBSTUDIO TRÊN Ổ /"
dux "$PROJECT_DIR" 2 30
run "ls -la '$PROJECT_DIR'/data '$PROJECT_DIR'/data/jobs 2>/dev/null | head -60"

sec "4. CHÊNH LỆCH du vs df TRÊN Ổ / (file bị che dưới mount point hoặc đã xóa nhưng còn mở)"
used_df=$(df -B1 --output=used / | tail -1 | tr -d ' ')
used_du=$(timeout "$DU_TIMEOUT" du -sxb / 2>/dev/null | cut -f1)
echo "df used : $(numfmt --to=iec "$used_df")"
echo "du used : $(numfmt --to=iec "${used_du:-0}")"
echo "chênh   : $(numfmt --to=iec $(( used_df - ${used_du:-0} )))  (vài GB là bình thường do metadata; lớn hơn nhiều → xem mục 5)"

sec "5. FILE ĐÃ XÓA NHƯNG PROCESS VẪN GIỮ (chiếm dung lượng mà du không thấy)"
for fd in /proc/[0-9]*/fd/*; do
  t=$(readlink "$fd" 2>/dev/null) || continue
  case "$t" in *"(deleted)"*) ;; *) continue ;; esac
  sz=$(stat -L -c %s "$fd" 2>/dev/null) || continue
  [ "$sz" -gt 10485760 ] || continue
  pid=${fd#/proc/}; pid=${pid%%/*}
  printf '%12s  pid=%-7s %-15s %s\n' "$(numfmt --to=iec "$sz")" "$pid" "$(cat /proc/$pid/comm 2>/dev/null)" "$t"
done | sort -rh | head -30
echo "(trống = không có file >10MB đã xóa còn mở)"

sec "6. 30 FILE LỚN NHẤT TRÊN Ổ / (>200MB)"
run "find / -xdev -type f -size +200M -printf '%s\t%TY-%Tm-%Td %TH:%TM\t%p\n' 2>/dev/null | sort -rn | head -30 | numfmt --field=1 --to=iec"

sec "7. FILE >10MB ĐƯỢC GHI TRONG 24 GIỜ QUA TRÊN Ổ / (thứ đang làm đầy ổ)"
run "find / -xdev -type f -size +10M -mmin -1440 -printf '%s\t%TY-%Tm-%Td %TH:%TM\t%p\n' 2>/dev/null | sort -rn | head -40 | numfmt --field=1 --to=iec"

sec "8. DOCKER / CONTAINERD"
run "docker info 2>/dev/null | grep -E 'Docker Root Dir|Storage Driver|containerd'"
run "cat /etc/docker/daemon.json 2>/dev/null"
run "grep -nE '^\s*(root|state)\s*=' /etc/containerd/config.toml 2>/dev/null"
run "du -sxh /var/lib/docker /var/lib/containerd /run/containerd 2>/dev/null"
run "docker system df 2>/dev/null"
run "docker ps -a -s --format 'table {{.Names}}\t{{.Status}}\t{{.Size}}\t{{.Image}}' 2>/dev/null"
run "docker inspect -f '{{range .Mounts}}{{.Type}}  {{.Source}} -> {{.Destination}}{{println}}{{end}}' $CONTAINER 2>/dev/null"

sec "9. CẤU HÌNH ĐƯỜNG DẪN BÊN TRONG CONTAINER (chỉ biến đường dẫn, không in API key)"
run "docker exec $CONTAINER env 2>/dev/null | grep -E '^(DATA_DIR|JOBS_DIR|HLS_STORAGE_PATH|HLS_UPLOAD_DIR|UPLOAD_DIR|OUTPUT_DIR|MODELS_DIR|TMPDIR|MODELSCOPE_CACHE)='"
run "docker exec $CONTAINER python -c \"import sys;sys.path.insert(0,'backend');from app.config import settings as s;print('data   :',s.data_dir);print('jobs   :',s.jobs_dir);print('hls    :',s.hls_storage_path);print('upload :',s.hls_upload_dir);print('models :',s.models_dir)\""
run "docker exec $CONTAINER sh -c 'df -h / /data /models /tmp /var/www/hls 2>/dev/null; du -sh /data/* /tmp /root/.cache 2>/dev/null'"

sec "10. FILE CẤU HÌNH TRÊN SERVER (có bị rỗng do lưu khi ổ đầy không?)"
run "ls -la '$PROJECT_DIR'/.env '$PROJECT_DIR'/docker-compose.yml '$PROJECT_DIR'/backend/app/config.py '$PROJECT_DIR'/backend/app/hls/router.py"
run "grep -nE '^\s*-\s' '$PROJECT_DIR'/docker-compose.yml"
run "grep -nE '^(DATA_DIR|JOBS_DIR|HLS_STORAGE_PATH|HLS_UPLOAD_DIR|UPLOAD_DIR|OUTPUT_DIR|MODELS_DIR|TMPDIR)=' '$PROJECT_DIR'/.env"
run "grep -n 'JOBS_DIR' '$PROJECT_DIR'/backend/app/config.py || echo '!! config.py CHƯA có JOBS_DIR'"
run "grep -n '/var/www/hls' '$PROJECT_DIR'/backend/app/hls/router.py || echo 'router.py: không còn đường dẫn cố định'"
run "cd '$PROJECT_DIR' && git status --short 2>/dev/null | head -30"

sec "11. PROCESS ĐANG CHẠY (ffmpeg / python)"
run "ps -eo pid,user,etime,pcpu,rss,args --sort=-pcpu | grep -E 'ffmpeg|uvicorn|python' | grep -v grep | cut -c1-300 | head -20"
for pid in $(pgrep -f ffmpeg); do
  echo "--- ffmpeg pid $pid: file đang mở để ghi"
  ls -l /proc/$pid/fd 2>/dev/null | grep -E '\.(ts|mp4|m4s|wav|m3u8|mkv)' | awk '{print $NF}'
done

sec "12. LOG & CACHE HỆ THỐNG"
run "journalctl --disk-usage"
run "find /var/log -xdev -type f -size +50M -printf '%s\t%p\n' 2>/dev/null | sort -rn | numfmt --field=1 --to=iec"
run "du -sxh /var/cache/apt /var/lib/snapd /snap /var/crash 2>/dev/null"
run "swapon --show"

sec "13. PHÂN VÙNG lv_hls (/var/www/hls)"
run "du -sh /var/www/hls/* /var/www/hls/substudio/* 2>/dev/null | sort -rh"

sec "XONG"
echo "Báo cáo đã lưu: $REPORT"
