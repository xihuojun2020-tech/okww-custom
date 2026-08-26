package com.okww.combatagent;

/** Dependency-free executable checks for the strict JSON parser. */
public final class JsonObjectSelfTest {
    public static void main(String[] args) throws Exception {
        JsonObject valid = JsonObject.parse("{ \"integer\": 0, \"decimal\": -12.50e+2, \"text\": \"ok\", \"none\": null }");
        if (valid.getString("text") == null || !valid.has("none") || valid.get("none") != null) fail("valid object");
        if (!valid.toString().contains("\"none\":null")) fail("null rendering");
        expectFailure("{\"x\":01}");
        expectFailure("{\"x\":-01}");
        expectFailure("{\"x\":1.}");
        expectFailure("{\"x\":1e}");
        expectFailure("{\"x\":1e+}");
        expectFailure("{\"x\":1,\"x\":2}");
        expectFailure("{\"nested\":{\"x\":1,\"x\":2}}");
        String pair = JsonObject.parse("{\"x\":\"\\uD834\\uDD1E\"}").getString("x");
        if (pair.length() != 2 || !Character.isHighSurrogate(pair.charAt(0)) || !Character.isLowSurrogate(pair.charAt(1))) fail("surrogate pair");
        expectFailure("{\"x\":\"\\uD834\"}");
        expectFailure("{\"x\":\"\\uDD1E\"}");
        expectFailure("{\"x\":\"\\uD834\\u0041\"}");
        expectFailure("{\u00a0\"x\":1}");
        expectFailure("{\u000b\"x\":1}");
        Protocol.Message identity = Protocol.parse("{\"protocol_version\":1,\"session_token\":\"session\",\"command_id\":\"identity\",\"kind\":\"heartbeat\",\"payload\":{\"identity\":true},\"issued_at\":1,\"deadline\":2,\"status\":\"accepted\"}");
        String identityPayload = AgentServer.heartbeatPayload(identity, "1.12.02").toString();
        if (!identityPayload.contains("\"build_version\":\"1.12.02\"") || !identityPayload.contains("\"protocol_version\":1")) fail("identity payload");
    }

    private static void expectFailure(String text) throws Exception {
        try { JsonObject.parse(text); fail("accepted invalid JSON: " + text); }
        catch (JsonObject.JsonException expected) { }
    }
    private static void fail(String message) throws Exception { throw new Exception(message); }
}
