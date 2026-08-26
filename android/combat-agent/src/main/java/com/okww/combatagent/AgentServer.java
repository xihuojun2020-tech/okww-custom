package com.okww.combatagent;

import android.net.LocalServerSocket;
import android.net.LocalSocket;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class AgentServer {
    private final String normalName;
    private final String emergencyName;
    private final String buildVersion;
    private final TouchScheduler scheduler;
    private final ExecutorService clients = Executors.newCachedThreadPool();
    private final Object sessionLock = new Object();
    private volatile String sessionToken;
    private volatile boolean running = true;
    private LocalServerSocket normal;
    private LocalServerSocket emergency;

    AgentServer(String normalName, String emergencyName, String buildVersion, TouchScheduler scheduler) {
        validateSocketName(normalName); validateSocketName(emergencyName);
        validateBuildVersion(buildVersion);
        if (normalName.equals(emergencyName)) throw new IllegalArgumentException("socket_names_must_differ");
        this.normalName = normalName; this.emergencyName = emergencyName; this.buildVersion = buildVersion; this.scheduler = scheduler;
    }

    void start() throws IOException {
        normal = new LocalServerSocket(normalName);
        emergency = new LocalServerSocket(emergencyName);
        Thread normalThread = new Thread(new Acceptor(normal, false), "okww-normal-accept");
        Thread emergencyThread = new Thread(new Acceptor(emergency, true), "okww-emergency-accept");
        normalThread.setDaemon(true); emergencyThread.setDaemon(true);
        normalThread.start(); emergencyThread.start();
    }

    void close() {
        running = false;
        closeSocket(normal); closeSocket(emergency);
        clients.shutdownNow();
        scheduler.releaseAll();
    }

    private final class Acceptor implements Runnable {
        private final LocalServerSocket server; private final boolean emergencyLane;
        Acceptor(LocalServerSocket server, boolean emergencyLane) { this.server = server; this.emergencyLane = emergencyLane; }
        public void run() {
            while (running) {
                try { final LocalSocket socket = server.accept(); clients.execute(new Client(socket, emergencyLane)); }
                catch (IOException e) { if (running) scheduler.releaseAll(); }
            }
        }
    }

    private final class Client implements Runnable {
        private final LocalSocket socket; private final boolean emergencyLane;
        Client(LocalSocket socket, boolean emergencyLane) { this.socket = socket; this.emergencyLane = emergencyLane; }
        public void run() {
            try {
                BoundedLineReader reader = new BoundedLineReader(socket.getInputStream(), Protocol.MAX_FRAME);
                BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8));
                String line;
                while (running && (line = reader.readFrame()) != null) {
                    handle(line, writer);
                }
            } catch (BoundedLineReader.FrameTooLargeException tooLarge) {
                // Close immediately: a peer must not be allowed to keep accumulating an oversized frame.
            } catch (BoundedLineReader.InvalidUtf8Exception invalidUtf8) {
                // Invalid UTF-8 cannot be correlated safely; close this client.
            } catch (Throwable ignored) {
                // A malformed client must not take down the agent.
            } finally {
                if (!emergencyLane) scheduler.releaseAll();
                else scheduler.releaseAll();
                closeSocket(socket);
            }
        }
        private void handle(String line, BufferedWriter writer) throws IOException {
            Protocol.Message message;
            try { message = Protocol.parse(line); }
            catch (Protocol.ProtocolException e) { writeFallback(writer, e.getMessage()); return; }
            if (!allowedOnLane(message.kind)) { write(writer, message, "rejected", reason("wrong_lane")); return; }
            if (Protocol.expired(message)) { write(writer, message, "rejected", reason("deadline_expired")); return; }
            synchronized (sessionLock) {
                if (sessionToken == null) sessionToken = message.session;
                else if (!sessionToken.equals(message.session)) { write(writer, message, "rejected", reason("session_token_mismatch")); return; }
            }
            write(writer, message, "accepted", new JsonObject());
            if ("heartbeat".equals(message.kind)) {
                scheduler.heartbeat();
                try { write(writer, message, "completed", heartbeatPayload(message, buildVersion)); }
                catch (JsonObject.JsonException e) { write(writer, message, "rejected", reason("invalid_identity_request")); }
                return;
            }
            if ("semantic_action".equals(message.kind)) {
                // No layout map is shipped until anchors are calibrated on the target emulator.
                write(writer, message, "rejected", reason("layout_not_configured")); return;
            }
            // These paths intentionally avoid any normal-action lock.
            if ("cancel".equals(message.kind)) scheduler.cancel();
            else if ("emergency_stop".equals(message.kind)) scheduler.emergencyStop();
            else if ("release_all".equals(message.kind)) scheduler.releaseAll();
            write(writer, message, "completed", new JsonObject());
        }
        private boolean allowedOnLane(String kind) {
            if (emergencyLane) return "heartbeat".equals(kind) || "cancel".equals(kind) || "emergency_stop".equals(kind) || "release_all".equals(kind);
            return "semantic_action".equals(kind) || "heartbeat".equals(kind);
        }
    }

    private static JsonObject reason(String value) {
        JsonObject result = new JsonObject(); try { result.put("reason", value); } catch (JsonObject.JsonException ignored) { }
        return result;
    }
    static JsonObject heartbeatPayload(Protocol.Message message, String buildVersion) throws JsonObject.JsonException {
        JsonObject payload = new JsonObject();
        if (!message.payload.has("identity")) return payload;
        if (!Boolean.TRUE.equals(message.payload.get("identity"))) throw new JsonObject.JsonException("identity_must_be_true");
        JsonObject identity = new JsonObject();
        identity.put("build_version", buildVersion).put("protocol_version", Protocol.VERSION);
        payload.put("identity", identity);
        return payload;
    }
    private static void write(BufferedWriter writer, Protocol.Message request, String status, JsonObject payload) throws IOException {
        try { writer.write(Protocol.response(request, status, payload).toString()); writer.newLine(); writer.flush(); }
        catch (JsonObject.JsonException e) { throw new IOException("response_encoding_failed", e); }
    }
    private static void writeFallback(BufferedWriter writer, String reason) throws IOException {
        // A malformed frame has no trustworthy correlation fields. Return a valid diagnostic frame and keep the socket alive.
        JsonObject result = new JsonObject();
        JsonObject payload = new JsonObject();
        try {
            payload.put("reason", reason == null ? "invalid_frame" : reason);
            double now = System.currentTimeMillis() / 1000.0;
            result.put("protocol_version", Protocol.VERSION).put("session_token", "invalid-frame")
                    .put("command_id", "invalid-frame").put("kind", "heartbeat").put("payload", payload)
                    .put("issued_at", now).put("deadline", now).put("status", "rejected");
        }
        catch (JsonObject.JsonException ignored) { }
        writer.write(result.toString()); writer.newLine(); writer.flush();
    }
    private static void closeSocket(LocalServerSocket socket) { if (socket != null) try { socket.close(); } catch (IOException ignored) { } }
    private static void closeSocket(LocalSocket socket) { if (socket != null) try { socket.close(); } catch (IOException ignored) { } }
    static void validateSocketName(String name) {
        if (name == null || name.length() < 1 || name.length() > 80 || !name.matches("[A-Za-z0-9_.-]+")) throw new IllegalArgumentException("unsafe_socket_name");
    }
    static void validateBuildVersion(String version) {
        if (version == null || version.trim().length() == 0 || version.getBytes(StandardCharsets.UTF_8).length > 256) throw new IllegalArgumentException("unsafe_build_version");
    }
}
