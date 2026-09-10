// A browser the server is holding, streamed to whoever is reading: frames
// arrive over a socket and are painted on a canvas, and what the reader does
// to the canvas goes back as the mouse and keyboard the browser sees.
import { useEffect, useRef } from "react";

type StreamMessage = { frame?: string; signed_in?: boolean; error?: string };

type Point = { x: number; y: number };

export function Screen({
  path,
  say,
  onDone,
}: {
  path: string;
  say(text: string, ok: boolean | null): void;
  onDone(): void;
}) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  // The callbacks are read through refs so the socket outlives a re-render:
  // a new handler identity must not tear the stream down and open another.
  const speak = useRef(say);
  const finish = useRef(onDone);
  speak.current = say;
  finish.current = onDone;

  useEffect(() => {
    const screen = canvas.current;
    if (screen === null) return;
    const context = screen.getContext("2d");
    if (context === null) return;
    speak.current("Starting a browser…", null);
    screen.focus();
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}${path}`);
    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      finish.current();
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as StreamMessage;
      if (message.error !== undefined) {
        speak.current(`Error: ${message.error}`, false);
        return;
      }
      if (message.signed_in === true) {
        speak.current("Signed in. You can enrol them now.", true);
        socket.close();
        done();
        return;
      }
      if (message.frame !== undefined) {
        const image = new Image();
        image.onload = () => context.drawImage(image, 0, 0, screen.width, screen.height);
        image.src = `data:image/jpeg;base64,${message.frame}`;
        speak.current("Sign in below.", null);
      }
    };
    socket.onclose = () => done();

    const at = (event: MouseEvent): Point => {
      const box = screen.getBoundingClientRect();
      return {
        x: (event.clientX - box.left) * (screen.width / box.width),
        y: (event.clientY - box.top) * (screen.height / box.height),
      };
    };
    const send = (payload: object) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
    };
    screen.onmousedown = (event) => {
      const point = at(event);
      send({ mouse: { action: "mousePressed", x: point.x, y: point.y } });
    };
    screen.onmouseup = (event) => {
      const point = at(event);
      send({ mouse: { action: "mouseReleased", x: point.x, y: point.y } });
    };
    screen.onmousemove = (event) => {
      const point = at(event);
      send({ mouse: { action: "mouseMoved", x: point.x, y: point.y, button: "none" } });
    };
    screen.onwheel = (event) => {
      event.preventDefault();
      const point = at(event);
      send({ wheel: { x: point.x, y: point.y, delta_x: event.deltaX, delta_y: event.deltaY } });
    };
    screen.onkeydown = (event) => {
      event.preventDefault();
      const text = event.key.length === 1 ? event.key : "";
      send({
        key: { action: text !== "" ? "keyDown" : "rawKeyDown", key: event.key, code: event.code, text },
      });
    };
    screen.onkeyup = (event) => {
      event.preventDefault();
      send({ key: { action: "keyUp", key: event.key, code: event.code } });
    };

    return () => {
      socket.onclose = null;
      socket.close();
      screen.onmousedown = null;
      screen.onmouseup = null;
      screen.onmousemove = null;
      screen.onwheel = null;
      screen.onkeydown = null;
      screen.onkeyup = null;
    };
  }, [path]);

  return <canvas ref={canvas} id="screen" width={1280} height={800} tabIndex={0} />;
}
