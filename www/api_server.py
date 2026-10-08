from flask import Flask, jsonify, request
import os
import socket
import time
import subprocess
from flask_cors import CORS

app = Flask(__name__)

CORS(app)

@app.route('/api/status')
def status():
    hostname = socket.gethostname()
    current_time = time.strftime('%Y-%m-%d %H:%M:%S')
    # Get uptime
    with open('/proc/uptime', 'r') as f:
        uptime_seconds = float(f.readline().split()[0])
    uptime_str = time.strftime('%H:%M:%S', time.gmtime(uptime_seconds))
    # Get IP address
    ip_address = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip_address = s.getsockname()[0]
        s.close()
    except Exception:
        ip_address = request.host.split(':')[0] if request.host else None
    # Get external IP address
    try:
        external_ip = subprocess.check_output(['curl', '-4', '-s', 'ident.me']).decode().strip()
    except Exception:
        external_ip = None
    return jsonify({
        'hostname': hostname,
        'time': current_time,
        'uptime': uptime_str,
        'ip': ip_address,
        'external_ip': external_ip
    })

@app.route('/api/restart', methods=['POST'])
def restart():
    # You may want to add authentication here in production
    subprocess.Popen(['sudo', 'reboot'])
    return jsonify({'status': 'restarting'})

@app.route('/api/services')
def services():
    def get_service_info(service):
        # Get status
        status_cmd = ['systemctl', 'is-active', service]
        try:
            status = subprocess.check_output(status_cmd).decode().strip()
        except Exception:
            status = 'unknown'
        # Get PID
        pid = None
        try:
            pid_cmd = ['systemctl', 'show', service, '--property=MainPID']
            pid_out = subprocess.check_output(pid_cmd).decode().strip()
            pid = pid_out.split('=')[1] if '=' in pid_out else None
        except Exception:
            pid = None
        return {'name': service, 'status': status, 'pid': pid}

    services_list = ['ser2net.service', 'api_server.service']
    result = [get_service_info(s) for s in services_list]
    return jsonify({'services': result})

@app.route('/api/restart_service', methods=['POST'])
def restart_service():
    data = request.get_json()
    service = data.get('service')
    if service not in ['ser2net.service', 'api_server.service']:
        return jsonify({'error': 'Invalid service'}), 400
    try:
        subprocess.check_call(['sudo', 'systemctl', 'restart', service])
        return jsonify({'status': 'restarted', 'service': service})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)