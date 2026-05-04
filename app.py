from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, join_room, emit
from flask_cors import CORS
import os, uuid
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'meetpro-2026-secret'
CORS(app)

# ✅ threading mode — no eventlet/gevent, works on any Python version
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading',
                    logger=False, engineio_logger=False)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

rooms        = {}
user_sockets = {}
socket_users = {}

def get_room(room_id):
    if room_id not in rooms:
        rooms[room_id] = {
            'id': room_id,
            'participants': {},
            'chat': [],
            'created_at': datetime.now().isoformat()
        }
    return rooms[room_id]

@app.route('/')
@app.route('/room/<room_id>')
def index(room_id=None):
    return send_from_directory(BASE_DIR, 'meeting.html')

@app.route('/api/create-room', methods=['POST'])
def create_room():
    room_id = str(uuid.uuid4())[:8].upper()
    get_room(room_id)
    return jsonify({'roomId': room_id})

@app.route('/api/room/<room_id>')
def room_info(room_id):
    if room_id not in rooms:
        return jsonify({'participants': 0, 'exists': False})
    r = rooms[room_id]
    return jsonify({'exists': True, 'participants': len(r['participants']),
                    'created_at': r['created_at']})

@socketio.on('join')
def on_join(data):
    room_id = data.get('roomId', '').upper().strip()
    name    = (data.get('name') or 'Guest').strip()[:40]
    user_id = data.get('userId') or str(uuid.uuid4())
    room = get_room(room_id)
    if len(room['participants']) >= 50:
        emit('error', {'message': 'Room is full (50/50).'})
        return
    join_room(room_id)
    user_sockets[user_id]     = request.sid
    socket_users[request.sid] = {'userId': user_id, 'roomId': room_id}
    participant = {
        'id': user_id, 'name': name,
        'joinedAt': datetime.now().isoformat(),
        'handRaised': False, 'videoOn': data.get('videoOn', True),
        'audioOn': data.get('audioOn', True), 'isScreenSharing': False,
    }
    room['participants'][user_id] = participant
    emit('room-joined', {
        'userId': user_id, 'roomId': room_id,
        'participants': [p for uid, p in room['participants'].items() if uid != user_id],
        'chatHistory': room['chat'][-100:],
    })
    emit('participant-joined', participant, to=room_id, skip_sid=request.sid)

@socketio.on('offer')
def on_offer(data):
    target_sid = user_sockets.get(data.get('targetUserId'))
    if target_sid:
        emit('offer', data, to=target_sid)

@socketio.on('answer')
def on_answer(data):
    target_sid = user_sockets.get(data.get('targetUserId'))
    if target_sid:
        emit('answer', data, to=target_sid)

@socketio.on('ice-candidate')
def on_ice(data):
    target_sid = user_sockets.get(data.get('targetUserId'))
    if target_sid:
        emit('ice-candidate', data, to=target_sid)

@socketio.on('chat-message')
def on_chat(data):
    room_id = (data.get('roomId') or '').upper()
    if room_id not in rooms:
        return
    msg = {
        'id': str(uuid.uuid4())[:8],
        'userId': data.get('userId'),
        'name': data.get('name', 'Guest'),
        'message': (data.get('message') or '').strip()[:500],
        'timestamp': datetime.now().isoformat(),
    }
    if not msg['message']:
        return
    rooms[room_id]['chat'].append(msg)
    if len(rooms[room_id]['chat']) > 500:
        rooms[room_id]['chat'] = rooms[room_id]['chat'][-500:]
    emit('chat-message', msg, to=room_id)

@socketio.on('raise-hand')
def on_raise_hand(data):
    room_id = (data.get('roomId') or '').upper()
    user_id = data.get('userId')
    if room_id in rooms and user_id in rooms[room_id]['participants']:
        rooms[room_id]['participants'][user_id]['handRaised'] = bool(data.get('raised'))
    emit('raise-hand', data, to=room_id)

@socketio.on('reaction')
def on_reaction(data):
    room_id = (data.get('roomId') or '').upper()
    emit('reaction', data, to=room_id, skip_sid=request.sid)

@socketio.on('media-state')
def on_media_state(data):
    room_id = (data.get('roomId') or '').upper()
    user_id = data.get('userId')
    if room_id in rooms and user_id in rooms[room_id]['participants']:
        p = rooms[room_id]['participants'][user_id]
        if 'videoOn'         in data: p['videoOn']         = data['videoOn']
        if 'audioOn'         in data: p['audioOn']         = data['audioOn']
        if 'isScreenSharing' in data: p['isScreenSharing'] = data['isScreenSharing']
    emit('media-state', data, to=room_id, skip_sid=request.sid)

@socketio.on('disconnect')
def on_disconnect():
    info = socket_users.pop(request.sid, None)
    if not info:
        return
    user_id = info['userId']
    room_id = info['roomId']
    user_sockets.pop(user_id, None)
    if room_id in rooms:
        rooms[room_id]['participants'].pop(user_id, None)
        emit('participant-left', {'userId': user_id}, to=room_id)
        if not rooms[room_id]['participants']:
            del rooms[room_id]

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
