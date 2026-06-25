# UzMAX Server

Unified FastAPI server for the UzMAX medical assistant, thermal camera, face
recognition, and ESP32 robot controls.

Run from the repository root:

```bash
python uzmax_server/main.py
# port 5000 is often taken by macOS AirPlay Receiver — override if needed:
UZMAX_PORT=5050 python uzmax_server/main.py
```

Open `https://127.0.0.1:<port>/` (or `https://YOUR_SERVER_IP:<port>/` from another
device on the same network).

## HTTPS is required for camera + microphone

The dashboard's face detection (camera) and voice assistant (microphone) use the
browser `getUserMedia` API. Browsers **block** it on `http://` origins unless the
host is `localhost`/`127.0.0.1`. So opening the dashboard over a LAN IP on plain
HTTP makes both the camera and the mic fail at once (you'll see `Camera: ...` /
`Microphone: ...` alerts and the bot never responds).

The server therefore serves **HTTPS** when a certificate is present at
`certs/uzmax.crt` + `certs/uzmax.key` (paths overridable via `UZMAX_SSL_CERT` /
`UZMAX_SSL_KEY`). It falls back to plain HTTP if no cert is found.

Generate a self-signed cert (include every IP/host you'll open it from in the SAN):

```bash
cd uzmax_server && mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
  -keyout certs/uzmax.key -out certs/uzmax.crt -subj "/CN=UzMAX" \
  -addext "subjectAltName=IP:YOUR_SERVER_IP,IP:127.0.0.1,DNS:localhost"
```

The cert is self-signed, so the browser shows a one-time "Not private" warning —
click **Advanced → Proceed**. After that the camera and mic work over the LAN.
