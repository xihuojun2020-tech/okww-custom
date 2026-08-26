package com.okww.combatagent;

import java.util.HashSet;
import java.util.Set;

final class Protocol {
    static final int VERSION = 1;
    static final int MAX_FRAME = 64 * 1024;
    static final String[] FIELDS = {"protocol_version", "session_token", "command_id", "kind", "payload", "issued_at", "deadline", "status"};
    static final Set<String> KINDS = set("semantic_action", "heartbeat", "cancel", "emergency_stop", "release_all");
    static final Set<String> TERMINAL = set("completed", "cancelled", "rejected");

    private static Set<String> set(String... values) {
        HashSet<String> result = new HashSet<String>();
        for (String value : values) result.add(value);
        return result;
    }

    static final class Message {
        final int version; final String session; final String id; final String kind;
        final JsonObject payload; final double issuedAt; final double deadline; final String status;
        Message(int version, String session, String id, String kind, JsonObject payload, double issuedAt, double deadline, String status) {
            this.version = version; this.session = session; this.id = id; this.kind = kind;
            this.payload = payload; this.issuedAt = issuedAt; this.deadline = deadline; this.status = status;
        }
    }

    static Message parse(String raw) throws ProtocolException {
        if (raw == null || raw.length() > MAX_FRAME) throw new ProtocolException("frame_too_large");
        try {
            JsonObject object = JsonObject.parse(raw);
            Set<String> allowed = set(FIELDS);
            for (String key : object.keys()) if (!allowed.contains(key)) throw new ProtocolException("unknown_field");
            for (String field : FIELDS) if (!object.has(field)) throw new ProtocolException("missing_field:" + field);
            int version = object.getInt("protocol_version");
            String session = boundedString(object.getString("session_token"), "session_token");
            String id = boundedString(object.getString("command_id"), "command_id");
            String kind = object.getString("kind");
            if (!KINDS.contains(kind)) throw new ProtocolException("unknown_kind");
            JsonObject payload = object.getObject("payload");
            double issued = finite(object.getDouble("issued_at"), "issued_at");
            double deadline = finite(object.getDouble("deadline"), "deadline");
            String status = object.getString("status");
            if (!"accepted".equals(status)) throw new ProtocolException("request_status_must_be_accepted");
            if (deadline < issued) throw new ProtocolException("invalid_deadline");
            if (version != VERSION) throw new ProtocolException("unsupported_protocol_version");
            if ("semantic_action".equals(kind)) {
                String action = payload.optString("action", "").trim();
                if (action.length() == 0) throw new ProtocolException("missing_action");
            }
            return new Message(version, session, id, kind, payload, issued, deadline, status);
        } catch (ProtocolException e) { throw e; }
        catch (JsonObject.JsonException | NumberFormatException e) { throw new ProtocolException("invalid_json"); }
    }

    static boolean expired(Message message) { return System.currentTimeMillis() / 1000.0 > message.deadline; }

    static JsonObject response(Message request, String status, JsonObject payload) throws JsonObject.JsonException {
        JsonObject result = new JsonObject();
        result.put("protocol_version", VERSION).put("session_token", request.session).put("command_id", request.id)
                .put("kind", request.kind).put("payload", payload == null ? new JsonObject() : payload)
                .put("issued_at", request.issuedAt).put("deadline", request.deadline).put("status", status);
        return result;
    }

    private static double finite(double value, String field) throws ProtocolException {
        if (Double.isNaN(value) || Double.isInfinite(value)) throw new ProtocolException("invalid_" + field);
        return value;
    }
    private static String boundedString(String value, String field) throws ProtocolException {
        if (value == null || value.trim().length() == 0 || value.length() > 256) throw new ProtocolException("invalid_" + field);
        return value.trim();
    }
    static final class ProtocolException extends Exception { ProtocolException(String reason) { super(reason); } }
}
