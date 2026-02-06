from flask import Flask, render_template_string, send_file, jsonify, request
from flask_socketio import SocketIO, emit
import serial
import serial.tools.list_ports
import threading
import time
from datetime import datetime
import csv
import os
#use print statements to debug


app = Flask(__name__)
app.config['SECRET_KEY'] = 'gauge_secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# Serial port configuration, should only be 9600
current_port = None
current_baud = 9600

# All Parameters found in Original template
gauge_data = {
    'current_value': 0.0,
    'offset': 0.0,
    'raw_value': 0.0,
    'min': None,
    'max': None,
    'count': 0,
    'button_count': 0,
    'connected': False,
    'tolerance': {
        'usl': None,  # Upper Spec Limit
        'lsl': None,  # Lower Spec Limit
        'std': None,  # Standard/Target
    },
    'ng_plus': 0,   # Count over USL
    'ng_minus': 0,  # Count under LSL
    'pass_count': 0,
    'sum': 0.0,     # For calculating average
}

# Data storage
continuous_log = []
important_log = []

# Serial connection
ser = None
buffer = b''
running = False
read_thread = None

# HTML Template by claude
HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gauge Monitor</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            color: white;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .connection-card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            margin-bottom: 20px;
        }
        .connection-header {
            font-size: 1.4em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 20px;
        }
        .connection-controls {
            display: grid;
            grid-template-columns: 2fr 1fr 1fr auto;
            gap: 15px;
            align-items: center;
        }
        select, input {
            padding: 12px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 1em;
            background: white;
        }
        select:focus, input:focus {
            outline: none;
            border-color: #667eea;
        }
        input[type="number"] {
            width: 100%;
        }
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 600;
        }
        .status-indicator.disconnected {
            background: #fee2e2;
            color: #991b1b;
        }
        .status-indicator.connected {
            background: #d1fae5;
            color: #065f46;
        }
        .status-indicator.checking {
            background: #fef3c7;
            color: #92400e;
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: currentColor;
        }
        
        .gauge-card {
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            margin-bottom: 20px;
            display: none;
        }
        .gauge-card.visible {
            display: block;
        }
        .gauge-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .gauge-title {
            font-size: 1.8em;
            font-weight: bold;
            color: #667eea;
        }
        .gauge-status {
            width: 15px;
            height: 15px;
            border-radius: 50%;
            background: #4ade80;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .reading-section {
            display: grid;
            grid-template-columns: 1fr 300px;
            gap: 30px;
            margin-bottom: 30px;
        }
        
        .value-display-container {
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .value-display {
            text-align: center;
            font-size: 5em;
            font-weight: bold;
            color: #1e293b;
            margin: 20px 0;
            font-variant-numeric: tabular-nums;
            transition: all 0.3s;
        }
        .value-display.pass {
            color: #10b981;
        }
        .value-display.fail {
            color: #ef4444;
        }
        .value-unit {
            font-size: 0.35em;
            color: #64748b;
        }
        .button-flash {
            animation: flash 0.3s;
        }
        @keyframes flash {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        .status-badge {
            text-align: center;
            padding: 10px 20px;
            border-radius: 10px;
            font-size: 1.2em;
            font-weight: bold;
            margin-top: 10px;
        }
        .status-badge.pass {
            background: #d1fae5;
            color: #065f46;
        }
        .status-badge.fail {
            background: #fee2e2;
            color: #991b1b;
        }
        .status-badge.neutral {
            background: #f1f5f9;
            color: #475569;
        }
        
        .tolerance-section {
            background: #f8fafc;
            padding: 20px;
            border-radius: 10px;
        }
        .tolerance-header {
            font-size: 1.1em;
            font-weight: bold;
            color: #475569;
            margin-bottom: 15px;
        }
        .tolerance-inputs {
            display: grid;
            gap: 12px;
        }
        .tolerance-input-group {
            display: grid;
            grid-template-columns: 80px 1fr;
            align-items: center;
            gap: 10px;
        }
        .tolerance-label {
            font-weight: 600;
            color: #64748b;
            font-size: 0.95em;
        }
        .tolerance-input {
            padding: 10px;
            border: 2px solid #e2e8f0;
            border-radius: 6px;
            font-size: 1em;
        }
        .tolerance-bar {
            width: 100%;
            height: 30px;
            background: linear-gradient(to right, 
                #fee2e2 0%, 
                #fee2e2 20%, 
                #d1fae5 20%, 
                #d1fae5 80%, 
                #fee2e2 80%, 
                #fee2e2 100%);
            border-radius: 5px;
            margin-top: 15px;
            position: relative;
        }
        .tolerance-marker {
            position: absolute;
            width: 3px;
            height: 100%;
            background: #1e293b;
            top: 0;
        }
        .tolerance-labels {
            display: flex;
            justify-content: space-between;
            margin-top: 5px;
            font-size: 0.85em;
            color: #64748b;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 15px;
            margin: 25px 0;
        }
        .stat {
            background: #f8fafc;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }
        .stat.ng-stat {
            background: #fee2e2;
        }
        .stat.pass-stat {
            background: #d1fae5;
        }
        .stat-label {
            font-size: 0.85em;
            color: #64748b;
            margin-bottom: 8px;
            font-weight: 600;
        }
        .stat-value {
            font-size: 1.8em;
            font-weight: bold;
            color: #1e293b;
        }
        .stat.ng-stat .stat-value {
            color: #991b1b;
        }
        .stat.pass-stat .stat-value {
            color: #065f46;
        }
        
        .controls {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-top: 25px;
        }
        button {
            padding: 15px;
            border: none;
            border-radius: 10px;
            font-size: 1.1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        button:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(0,0,0,0.2);
        }
        button:active:not(:disabled) {
            transform: translateY(0);
        }
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .btn-primary {
            background: #3b82f6;
            color: white;
        }
        .btn-success {
            background: #10b981;
            color: white;
        }
        .btn-secondary {
            background: #8b5cf6;
            color: white;
        }
        .btn-danger {
            background: #ef4444;
            color: white;
        }
        .btn-warning {
            background: #f59e0b;
            color: white;
        }
        .btn-large {
            font-size: 1.3em;
        }
        
        .data-section {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 20px;
        }
        .data-log {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            display: none;
        }
        .data-log.visible {
            display: block;
        }
        .log-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #e2e8f0;
        }
        .log-title {
            font-size: 1.4em;
            font-weight: bold;
            color: #667eea;
        }
        .log-badge {
            background: #667eea;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
        }
        .btn-small {
            padding: 8px 15px;
            font-size: 0.9em;
        }
        .export-controls {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .filename-input {
            padding: 8px;
            border-radius: 5px;
            border: 2px solid #e2e8f0;
            width: 150px;
            font-size: 0.9em;
        }
        .log-table {
            width: 100%;
            max-height: 400px;
            overflow-y: auto;
            display: block;
        }
        .log-table table {
            width: 100%;
            border-collapse: collapse;
        }
        .log-table thead {
            background: #f8fafc;
            position: sticky;
            top: 0;
        }
        .log-table th, .log-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }
        .log-table th {
            font-weight: 600;
            color: #475569;
            font-size: 0.9em;
        }
        .log-table tr:hover {
            background: #f8fafc;
        }
        .log-table tr.pass-row {
            background: #f0fdf4;
        }
        .log-table tr.fail-row {
            background: #fef2f2;
        }
        .type-button {
            color: #ef4444;
            font-weight: bold;
        }
        .type-manual {
            color: #10b981;
            font-weight: bold;
        }
        .err-badge {
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: bold;
        }
        .err-badge.pass {
            background: #d1fae5;
            color: #065f46;
        }
        .err-badge.plus {
            background: #fee2e2;
            color: #991b1b;
        }
        .err-badge.minus {
            background: #fee2e2;
            color: #991b1b;
        }
        
        @media (max-width: 1024px) {
            .reading-section {
                grid-template-columns: 1fr;
            }
            .data-section {
                grid-template-columns: 1fr;
            }
            .controls {
                grid-template-columns: 1fr 1fr;
            }
            .connection-controls {
                grid-template-columns: 1fr;
            }
            .export-controls {
                flex-direction: column;
                align-items: stretch;
            }
            .filename-input {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Gauge Monitor</h1>
        
        <div class="connection-card">
            <div class="connection-header">Connection</div>
            <div class="connection-controls">
                <select id="portSelect" onchange="updateBaudOptions()">
                    <option value="">Select COM port...</option>
                </select>
                <select id="baudSelect">
                    <option value="9600">9600</option>
                    <option value="115200">115200</option>
                    <option value="4800">4800</option>
                    <option value="19200">19200</option>
                </select>
                <button class="btn-primary" id="connectBtn" onclick="toggleConnection()">Connect</button>
                <div class="status-indicator disconnected" id="status">
                    <div class="status-dot"></div>
                    <span>Disconnected</span>
                </div>
            </div>
        </div>
        
        <div class="gauge-card" id="gaugeCard">
            <div class="gauge-header">
                <div class="gauge-title">Digital Indicator</div>
                <div class="gauge-status"></div>
            </div>
            
            <div class="reading-section">
                <div class="value-display-container">
                    <div class="value-display neutral" id="value">---<span class="value-unit">mm</span></div>
                    <div class="status-badge neutral" id="statusBadge">Waiting...</div>
                </div>
                
                <div class="tolerance-section">
                    <div class="tolerance-header">Tolerance Settings</div>
                    <div class="tolerance-inputs">
                        <div class="tolerance-input-group">
                            <label class="tolerance-label">USL:</label>
                            <input type="number" step="0.001" class="tolerance-input" id="uslInput" 
                                   placeholder="Upper limit" onchange="updateTolerance()">
                        </div>
                        <div class="tolerance-input-group">
                            <label class="tolerance-label">STD:</label>
                            <input type="number" step="0.001" class="tolerance-input" id="stdInput" 
                                   placeholder="Standard" onchange="updateTolerance()">
                        </div>
                        <div class="tolerance-input-group">
                            <label class="tolerance-label">LSL:</label>
                            <input type="number" step="0.001" class="tolerance-input" id="lslInput" 
                                   placeholder="Lower limit" onchange="updateTolerance()">
                        </div>
                    </div>
                    <div class="tolerance-bar" id="toleranceBar"></div>
                    <div class="tolerance-labels">
                        <span id="lslLabel">LSL</span>
                        <span id="stdLabel">STD</span>
                        <span id="uslLabel">USL</span>
                    </div>
                </div>
            </div>
            
            <div class="stats-grid">
                <div class="stat">
                    <div class="stat-label">Minimum</div>
                    <div class="stat-value" id="min">---</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Maximum</div>
                    <div class="stat-value" id="max">---</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Average</div>
                    <div class="stat-value" id="avg">---</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Range</div>
                    <div class="stat-value" id="range">---</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Total</div>
                    <div class="stat-value" id="count">0</div>
                </div>
                <div class="stat" style="background: #dbeafe;">
                    <div class="stat-label">Button Presses</div>
                    <div class="stat-value" id="buttonCount" style="color: #1e40af;">0</div>
                </div>
                <div class="stat pass-stat">
                    <div class="stat-label">Pass</div>
                    <div class="stat-value" id="passCount">0</div>
                </div>
                <div class="stat ng-stat">
                    <div class="stat-label">+NG</div>
                    <div class="stat-value" id="ngPlus">0</div>
                </div>
                <div class="stat ng-stat">
                    <div class="stat-label">-NG</div>
                    <div class="stat-value" id="ngMinus">0</div>
                </div>
            </div>
            
            <div class="controls">
                <button class="btn-primary" onclick="zero()">Zero Gauge</button>
                <button class="btn-success btn-large" onclick="capture()">Capture</button>
                <button class="btn-warning" onclick="resetStats()">Reset Stats</button>
                <button class="btn-secondary" onclick="exportImportant()">Export Important</button>
            </div>
        </div>
        
        <div class="data-section">
            <div class="data-log" id="importantLog">
                <div class="log-header">
                    <div class="log-title">Important Captures</div>
                    <div class="export-controls">
                        <span class="log-badge" id="importantCount">0</span>
                        <input type="text" id="importantFilename" class="filename-input" placeholder="filename (optional)">
                        <button class="btn-secondary btn-small" onclick="exportImportant()">Export</button>
                    </div>
                </div>
                <div class="log-table">
                    <table>
                        <thead>
                            <tr>
                                <th>No.</th>
                                <th>Time</th>
                                <th>Value (mm)</th>
                                <th>Err</th>
                                <th>Type</th>
                            </tr>
                        </thead>
                        <tbody id="importantLogBody"></tbody>
                    </table>
                </div>
            </div>
            
            <div class="data-log" id="continuousLog">
                <div class="log-header">
                    <div class="log-title">Continuous Log</div>
                    <div class="export-controls">
                        <input type="text" id="continuousFilename" class="filename-input" placeholder="filename (optional)">
                        <button class="btn-secondary btn-small" onclick="exportContinuous()">Export All</button>
                    </div>
                </div>
                <div class="log-table">
                    <table>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Value (mm)</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody id="continuousLogBody"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        const socket = io();
        let importantData = [];
        let continuousData = [];
        let isConnected = false;
        let tolerance = {usl: null, lsl: null, std: null};
        
        // Load COM ports on page load
        window.onload = () => {
            loadPorts();
        };
        
        function loadPorts() {
            fetch('/api/ports')
                .then(r => r.json())
                .then(data => {
                    const select = document.getElementById('portSelect');
                    select.innerHTML = '<option value="">Select COM port...</option>';
                    data.ports.forEach(port => {
                        const option = document.createElement('option');
                        option.value = port.device;
                        option.textContent = `${port.device} - ${port.description}`;
                        select.appendChild(option);
                    });
                });
        }
        
        function updateBaudOptions() {
            // Could auto-detect baud in future
        }
        
        function toggleConnection() {
            if (!isConnected) {
                connect();
            } else {
                disconnect();
            }
        }
        
        function connect() {
            const port = document.getElementById('portSelect').value;
            const baud = document.getElementById('baudSelect').value;
            
            if (!port) {
                alert('Please select a COM port');
                return;
            }
            
            setStatus('checking', 'Connecting...');
            document.getElementById('connectBtn').disabled = true;
            
            fetch('/api/connect', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({port: port, baud: parseInt(baud)})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    isConnected = true;
                    setStatus('connected', 'Connected');
                    document.getElementById('connectBtn').textContent = 'Disconnect';
                    document.getElementById('connectBtn').classList.remove('btn-primary');
                    document.getElementById('connectBtn').classList.add('btn-danger');
                    document.getElementById('gaugeCard').classList.add('visible');
                    document.getElementById('importantLog').classList.add('visible');
                    document.getElementById('continuousLog').classList.add('visible');
                } else {
                    setStatus('disconnected', 'Connection Failed');
                    alert('Failed to connect: ' + data.error);
                }
                document.getElementById('connectBtn').disabled = false;
            })
            .catch(err => {
                setStatus('disconnected', 'Connection Error');
                alert('Error: ' + err);
                document.getElementById('connectBtn').disabled = false;
            });
        }
        
        function disconnect() {
            fetch('/api/disconnect', {method: 'POST'})
            .then(r => r.json())
            .then(data => {
                isConnected = false;
                setStatus('disconnected', 'Disconnected');
                document.getElementById('connectBtn').textContent = 'Connect';
                document.getElementById('connectBtn').classList.remove('btn-danger');
                document.getElementById('connectBtn').classList.add('btn-primary');
                document.getElementById('gaugeCard').classList.remove('visible');
                document.getElementById('importantLog').classList.remove('visible');
                document.getElementById('continuousLog').classList.remove('visible');
            });
        }
        
        function setStatus(type, text) {
            const status = document.getElementById('status');
            status.className = `status-indicator ${type}`;
            status.querySelector('span').textContent = text;
        }
        
        function updateTolerance() {
            const usl = parseFloat(document.getElementById('uslInput').value);
            const lsl = parseFloat(document.getElementById('lslInput').value);
            const std = parseFloat(document.getElementById('stdInput').value);
            
            tolerance.usl = isNaN(usl) ? null : usl;
            tolerance.lsl = isNaN(lsl) ? null : lsl;
            tolerance.std = isNaN(std) ? null : std;
            
            // Send to server
            socket.emit('update_tolerance', tolerance);
            
            // Update labels
            document.getElementById('uslLabel').textContent = tolerance.usl !== null ? tolerance.usl.toFixed(3) : 'USL';
            document.getElementById('lslLabel').textContent = tolerance.lsl !== null ? tolerance.lsl.toFixed(3) : 'LSL';
            document.getElementById('stdLabel').textContent = tolerance.std !== null ? tolerance.std.toFixed(3) : 'STD';
        }
        
        function checkTolerance(value) {
            if (tolerance.usl !== null && value > tolerance.usl) return 'over';
            if (tolerance.lsl !== null && value < tolerance.lsl) return 'under';
            if (tolerance.usl !== null || tolerance.lsl !== null) return 'pass';
            return 'none';
        }
        
        function getErrBadge(status) {
            if (status === 'over') return '<span class="err-badge plus">+Err</span>';
            if (status === 'under') return '<span class="err-badge minus">-Err</span>';
            if (status === 'pass') return '<span class="err-badge pass">Pass</span>';
            return '';
        }
        
        socket.on('gauge_data', (data) => {
            const valueEl = document.getElementById('value');
            const statusBadge = document.getElementById('statusBadge');
            
            valueEl.innerHTML = data.value.toFixed(3) + '<span class="value-unit">mm</span>';
            
            // Update status based on tolerance
            const status = checkTolerance(data.value);
            valueEl.className = 'value-display';
            statusBadge.className = 'status-badge';
            
            if (status === 'pass') {
                valueEl.classList.add('pass');
                statusBadge.classList.add('pass');
                statusBadge.textContent = 'PASS';
            } else if (status === 'over') {
                valueEl.classList.add('fail');
                statusBadge.classList.add('fail');
                statusBadge.textContent = 'FAIL (+NG)';
            } else if (status === 'under') {
                valueEl.classList.add('fail');
                statusBadge.classList.add('fail');
                statusBadge.textContent = 'FAIL (-NG)';
            } else {
                valueEl.classList.add('neutral');
                statusBadge.classList.add('neutral');
                statusBadge.textContent = 'No Tolerance Set';
            }
            
            if (data.button) {
                valueEl.classList.add('button-flash');
                setTimeout(() => valueEl.classList.remove('button-flash'), 300);
            }
            
            // Update tolerance marker
            if (tolerance.usl !== null && tolerance.lsl !== null) {
                const range = tolerance.usl - tolerance.lsl;
                const position = ((data.value - tolerance.lsl) / range) * 100;
                const marker = document.querySelector('.tolerance-marker');
                if (!marker) {
                    const newMarker = document.createElement('div');
                    newMarker.className = 'tolerance-marker';
                    document.getElementById('toleranceBar').appendChild(newMarker);
                }
                document.querySelector('.tolerance-marker').style.left = Math.max(0, Math.min(100, position)) + '%';
            }
            
            // Update stats
            document.getElementById('count').textContent = data.count;
            document.getElementById('buttonCount').textContent = data.button_count;
            document.getElementById('passCount').textContent = data.pass_count;
            document.getElementById('ngPlus').textContent = data.ng_plus;
            document.getElementById('ngMinus').textContent = data.ng_minus;
            
            if (data.min !== null) {
                document.getElementById('min').textContent = data.min.toFixed(3);
            }
            if (data.max !== null) {
                document.getElementById('max').textContent = data.max.toFixed(3);
            }
            if (data.avg !== null) {
                document.getElementById('avg').textContent = data.avg.toFixed(3);
            }
            if (data.range !== null) {
                document.getElementById('range').textContent = data.range.toFixed(3);
            }
        });
        
        socket.on('important_capture', (data) => {
            addToImportantLog(data.time, data.value, data.type, data.status);
        });
        
        socket.on('continuous_update', (data) => {
            addToContinuousLog(data.time, data.value, data.status);
        });
        
        function addToImportantLog(time, value, type, status) {
            const tbody = document.getElementById('importantLogBody');
            const row = tbody.insertRow(0);
            
            const rowClass = status === 'pass' ? 'pass-row' : (status !== 'none' ? 'fail-row' : '');
            row.className = rowClass;
            
            const typeClass = type === 'Button' ? 'type-button' : 'type-manual';
            
            const count = tbody.rows.length;
            row.insertCell(0).textContent = count;
            row.insertCell(1).textContent = time;
            row.insertCell(2).textContent = value.toFixed(3);
            row.insertCell(3).innerHTML = getErrBadge(status);
            const typeCell = row.insertCell(4);
            typeCell.textContent = type;
            typeCell.className = typeClass;
            
            importantData.unshift({time, value, type, status});
            document.getElementById('importantCount').textContent = importantData.length;
        }
        
        function addToContinuousLog(time, value, status) {
            const tbody = document.getElementById('continuousLogBody');
            
            if (tbody.rows.length > 100) {
                tbody.deleteRow(100);
            }
            
            const row = tbody.insertRow(0);
            const rowClass = status === 'pass' ? 'pass-row' : (status !== 'none' ? 'fail-row' : '');
            row.className = rowClass;
            
            row.insertCell(0).textContent = time;
            row.insertCell(1).textContent = value.toFixed(3);
            row.insertCell(2).innerHTML = getErrBadge(status);
            
            continuousData.push({time, value, status});
        }
        
        function zero() {
            socket.emit('command', {cmd: 'zero'});
        }
        
        function capture() {
            socket.emit('command', {cmd: 'capture'});
        }
        
        function resetStats() {
            if (confirm('Reset all statistics? This will not delete captured data.')) {
                socket.emit('command', {cmd: 'reset_stats'});
            }
        }
        
        function exportImportant() {
            let filename = document.getElementById('importantFilename').value.trim();
            
            if (!filename) {
                const timestamp = new Date().toISOString().slice(0,19).replace(/:/g,'-');
                filename = `important_data_${timestamp}`;
            }
            
            if (!filename.endsWith('.csv')) {
                filename += '.csv';
            }
            
            window.location.href = `/export/important?filename=${encodeURIComponent(filename)}`;
        }
        
        function exportContinuous() {
            let filename = document.getElementById('continuousFilename').value.trim();
            
            if (!filename) {
                const timestamp = new Date().toISOString().slice(0,19).replace(/:/g,'-');
                filename = `continuous_data_${timestamp}`;
            }
            
            if (!filename.endsWith('.csv')) {
                filename += '.csv';
            }
            
            window.location.href = `/export/continuous?filename=${encodeURIComponent(filename)}`;
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/ports')
def get_ports():
    ports = serial.tools.list_ports.comports()
    port_list = [{'device': p.device, 'description': p.description} for p in ports]
    return jsonify({'ports': port_list})

@app.route('/api/connect', methods=['POST'])
def connect():
    global ser, running, read_thread, current_port, current_baud, buffer
    
    data = request.json
    port = data.get('port')
    baud = data.get('baud', 9600)
    
    try:
        # Close existing connection
        if ser and ser.is_open:
            ser.close()
        
        # Open new connection
        ser = serial.Serial(port, baud, timeout=0.1)
        ser.reset_input_buffer()
        buffer = b''
        
        current_port = port
        current_baud = baud
        gauge_data['connected'] = True
        
        # Reset all parameters
        gauge_data['count'] = 0
        gauge_data['button_count'] = 0
        gauge_data['min'] = None
        gauge_data['max'] = None
        gauge_data['ng_plus'] = 0
        gauge_data['ng_minus'] = 0
        gauge_data['pass_count'] = 0
        gauge_data['sum'] = 0.0
        continuous_log.clear()
        important_log.clear()
        
        # Start reading thread
        if read_thread and read_thread.is_alive():
            running = False
            read_thread.join(timeout=1)
        
        running = True
        read_thread = threading.Thread(target=read_serial, daemon=True)
        read_thread.start()
        
        time.sleep(0.5)
        
        return jsonify({'success': True, 'port': port, 'baud': baud})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    global ser, running
    
    running = False
    if ser and ser.is_open:
        ser.close()
    gauge_data['connected'] = False
    
    return jsonify({'success': True})

@app.route('/export/important')
def export_important():
    custom_name = request.args.get('filename', '')
    if custom_name:
        filename = custom_name
    else:
        filename = f'important_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    filepath = os.path.join(os.getcwd(), filename)
    
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['No.', 'Timestamp', 'Value (mm)', 'Status', 'Type'])
        for idx, row in enumerate(important_log, 1):
            status_text = row.get('status', 'none')
            if status_text == 'over':
                status_text = '+Err'
            elif status_text == 'under':
                status_text = '-Err'
            elif status_text == 'pass':
                status_text = 'Pass'
            else:
                status_text = ''
            writer.writerow([idx, row['time'], f"{row['value']:.3f}", status_text, row['type']])
    
    return send_file(filepath, as_attachment=True, download_name=filename)

@app.route('/export/continuous')
def export_continuous():
    custom_name = request.args.get('filename', '')
    if custom_name:
        filename = custom_name
    else:
        filename = f'continuous_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    filepath = os.path.join(os.getcwd(), filename)
    
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Timestamp', 'Value (mm)', 'Status'])
        for row in continuous_log:
            status_text = row.get('status', 'none')
            if status_text == 'over':
                status_text = '+Err'
            elif status_text == 'under':
                status_text = '-Err'
            elif status_text == 'pass':
                status_text = 'Pass'
            else:
                status_text = ''
            writer.writerow([row['time'], f"{row['value']:.3f}", status_text])
    
    return send_file(filepath, as_attachment=True, download_name=filename)

@socketio.on('update_tolerance')
def handle_tolerance(data):
    global gauge_data
    gauge_data['tolerance']['usl'] = data.get('usl')
    gauge_data['tolerance']['lsl'] = data.get('lsl')
    gauge_data['tolerance']['std'] = data.get('std')
    print(f"Tolerance updated: USL={data.get('usl')}, LSL={data.get('lsl')}, STD={data.get('std')}")

@socketio.on('command')
def handle_command(data):
    global gauge_data
    
    cmd = data.get('cmd')
    
    if cmd == 'zero':
        gauge_data['offset'] = gauge_data['raw_value']
        print(f"Zeroed at {gauge_data['offset']:.3f}mm")
    
    elif cmd == 'reset_stats':
        gauge_data['count'] = 0
        gauge_data['button_count'] = 0
        gauge_data['min'] = None
        gauge_data['max'] = None
        gauge_data['ng_plus'] = 0
        gauge_data['ng_minus'] = 0
        gauge_data['pass_count'] = 0
        gauge_data['sum'] = 0.0
        print("Statistics reset")
    
    elif cmd == 'capture':
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        value = gauge_data['current_value']
        
        # Check tolerance
        status = check_tolerance(value)
        
        important_log.append({
            'time': timestamp,
            'value': value,
            'type': 'Manual',
            'status': status
        })
        
        socketio.emit('important_capture', {
            'time': timestamp,
            'value': value,
            'type': 'Manual',
            'status': status
        })
        
        print(f"Manual capture: {value:.3f}mm [{status}]")

def check_tolerance(value):
    usl = gauge_data['tolerance']['usl']
    lsl = gauge_data['tolerance']['lsl']
    
    if usl is not None and value > usl:
        return 'over'
    if lsl is not None and value < lsl:
        return 'under'
    if usl is not None or lsl is not None:
        return 'pass'
    return 'none'

def read_serial():
    global ser, buffer, running, gauge_data, continuous_log, important_log
    
    while running and ser and ser.is_open:
        try:
            if ser.in_waiting > 0:
                buffer += ser.read(ser.in_waiting)
                
                while len(buffer) >= 11:
                    if (buffer[0] == 0x12 and 
                        buffer[1] in [ord('+'), ord('-')] and 
                        buffer[2] == 0x00 and
                        buffer[9] == 0x0D):
                        
                        packet = buffer[:11]
                        buffer = buffer[11:]
                        
                        sign = chr(packet[1])
                        digits = ''.join([chr(b) for b in packet[3:9] if 48 <= b <= 57])
                        
                        if len(digits) == 6:
                            raw_value = float(digits) / 1000
                            if sign == '-':
                                raw_value = -raw_value
                            
                            gauge_data['raw_value'] = raw_value
                            zeroed_value = raw_value - gauge_data['offset']
                            gauge_data['current_value'] = zeroed_value
                            
                            # Update stats
                            gauge_data['count'] += 1
                            gauge_data['sum'] += zeroed_value
                            
                            if gauge_data['min'] is None or zeroed_value < gauge_data['min']:
                                gauge_data['min'] = zeroed_value
                            if gauge_data['max'] is None or zeroed_value > gauge_data['max']:
                                gauge_data['max'] = zeroed_value
                            
                            # Check tolerance
                            status = check_tolerance(zeroed_value)
                            if status == 'over':
                                gauge_data['ng_plus'] += 1
                            elif status == 'under':
                                gauge_data['ng_minus'] += 1
                            elif status == 'pass':
                                gauge_data['pass_count'] += 1
                            
                            # Calculate average +  range
                            avg = gauge_data['sum'] / gauge_data['count'] if gauge_data['count'] > 0 else None
                            range_val = (gauge_data['max'] - gauge_data['min']) if (gauge_data['min'] is not None and gauge_data['max'] is not None) else None
                            
                            is_button = (packet[10] == 0x0A)
                            if is_button:
                                gauge_data['button_count'] += 1
                            
                            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                            
                            continuous_log.append({
                                'time': timestamp,
                                'value': zeroed_value,
                                'status': status
                            })
                            
                            socketio.emit('continuous_update', {
                                'time': timestamp,
                                'value': zeroed_value,
                                'status': status
                            })
                            
                            if is_button:
                                important_log.append({
                                    'time': timestamp,
                                    'value': zeroed_value,
                                    'type': 'Button',
                                    'status': status
                                })
                                
                                socketio.emit('important_capture', {
                                    'time': timestamp,
                                    'value': zeroed_value,
                                    'type': 'Button',
                                    'status': status
                                })
                            
                            socketio.emit('gauge_data', {
                                'value': zeroed_value,
                                'min': gauge_data['min'],
                                'max': gauge_data['max'],
                                'avg': avg,
                                'range': range_val,
                                'count': gauge_data['count'],
                                'button_count': gauge_data['button_count'],
                                'pass_count': gauge_data['pass_count'],
                                'ng_plus': gauge_data['ng_plus'],
                                'ng_minus': gauge_data['ng_minus'],
                                'button': is_button
                            })
                    else:
                        buffer = buffer[1:]
                        
        except Exception as e:
            print(f"Read error: {e}")
            time.sleep(0.1)
        
        time.sleep(0.01)


#for it to run
if __name__ == '__main__':
    print("\n" + "="*50)
    print("Gauge Monitor Start")
    print("="*50)
    print("\nOpen browser to: http://localhost:5000")
    print("="*50 + "\n")
    
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nclosing")
        running = False