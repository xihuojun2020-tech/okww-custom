package com.okww.combatagent;

import java.util.LinkedHashMap;
import java.util.Map;
import java.math.BigDecimal;

/** Small strict JSON object parser used because the minimal android.jar has no org.json. */
final class JsonObject {
    private final LinkedHashMap<String, Object> values = new LinkedHashMap<String, Object>();

    static JsonObject parse(String text) throws JsonException {
        if (text == null) throw new JsonException("null_json");
        Parser parser = new Parser(text);
        JsonObject object = parser.object();
        parser.skip();
        if (!parser.end()) throw new JsonException("trailing_json");
        return object;
    }

    boolean has(String key) { return values.containsKey(key); }
    Object get(String key) throws JsonException { if (!has(key)) throw new JsonException("missing:" + key); return values.get(key); }
    String getString(String key) throws JsonException { Object value = get(key); if (!(value instanceof String)) throw new JsonException("not_string:" + key); return (String) value; }
    int getInt(String key) throws JsonException { Object value = get(key); if (!(value instanceof Number)) throw new JsonException("not_number:" + key); double number = ((Number) value).doubleValue(); if (Double.isNaN(number) || Double.isInfinite(number) || number != Math.rint(number) || number < Integer.MIN_VALUE || number > Integer.MAX_VALUE) throw new JsonException("invalid_int:" + key); return (int) number; }
    double getDouble(String key) throws JsonException { Object value = get(key); if (!(value instanceof Number)) throw new JsonException("not_number:" + key); return ((Number) value).doubleValue(); }
    String optString(String key, String fallback) { Object value = values.get(key); return value instanceof String ? (String) value : fallback; }
    JsonObject getObject(String key) throws JsonException { Object value = get(key); if (!(value instanceof JsonObject)) throw new JsonException("not_object:" + key); return (JsonObject) value; }
    JsonObject put(String key, Object value) throws JsonException { if (key == null) throw new JsonException("null_object_key"); if (values.containsKey(key)) throw new JsonException("duplicate_key:" + key); values.put(key, value); return this; }
    Iterable<String> keys() { return values.keySet(); }

    public String toString() { StringBuilder output = new StringBuilder(); output.append('{'); boolean first = true; for (Map.Entry<String, Object> entry : values.entrySet()) { if (!first) output.append(','); first = false; output.append(quote(entry.getKey())).append(':').append(render(entry.getValue())); } return output.append('}').toString(); }
    private static String render(Object value) { if (value instanceof String) return quote((String) value); if (value instanceof JsonObject) return value.toString(); if (value instanceof Boolean || value instanceof Number) return value.toString(); return "null"; }
    private static String quote(String value) { StringBuilder output = new StringBuilder(); output.append('"'); for (int i = 0; i < value.length(); i++) { char c = value.charAt(i); switch (c) { case '"': output.append("\\\""); break; case '\\': output.append("\\\\"); break; case '\b': output.append("\\b"); break; case '\f': output.append("\\f"); break; case '\n': output.append("\\n"); break; case '\r': output.append("\\r"); break; case '\t': output.append("\\t"); break; default: if (c < 0x20) output.append(String.format("\\u%04x", (int) c)); else output.append(c); } } return output.append('"').toString(); }

    static final class JsonException extends Exception { JsonException(String message) { super(message); } }
    private static final class Parser {
        private final String text; private int position;
        Parser(String text) { this.text = text; }
        boolean end() { return position == text.length(); }
        void skip() { while (position < text.length()) { char c = text.charAt(position); if (c == ' ' || c == '\t' || c == '\r' || c == '\n') position++; else break; } }
        JsonObject object() throws JsonException { skip(); if (!take('{')) throw error("object_expected"); JsonObject result = new JsonObject(); skip(); if (take('}')) return result; while (true) { skip(); String key = string(); skip(); if (!take(':')) throw error("colon_expected"); result.put(key, value()); skip(); if (take('}')) return result; if (!take(',')) throw error("comma_expected"); } }
        Object value() throws JsonException { skip(); if (position >= text.length()) throw error("value_expected"); char c = text.charAt(position); if (c == '{') return object(); if (c == '"') return string(); if (text.startsWith("true", position)) { position += 4; return Boolean.TRUE; } if (text.startsWith("false", position)) { position += 5; return Boolean.FALSE; } if (text.startsWith("null", position)) { position += 4; return null; } return number(); }
        String string() throws JsonException { if (!take('"')) throw error("string_expected"); StringBuilder result = new StringBuilder(); while (position < text.length()) { char c = text.charAt(position++); if (c == '"') return result.toString(); if (c == '\\') { if (position >= text.length()) throw error("escape_expected"); char escaped = text.charAt(position++); switch (escaped) { case '"': result.append('"'); break; case '\\': result.append('\\'); break; case '/': result.append('/'); break; case 'b': result.append('\b'); break; case 'f': result.append('\f'); break; case 'n': result.append('\n'); break; case 'r': result.append('\r'); break; case 't': result.append('\t'); break; case 'u': appendEscapedUnicode(result); break; default: throw error("invalid_escape"); } } else { if (c < 0x20) throw error("control_character"); if (Character.isHighSurrogate(c)) { if (position >= text.length() || !Character.isLowSurrogate(text.charAt(position))) throw error("invalid_surrogate"); result.append(c).append(text.charAt(position++)); } else if (Character.isLowSurrogate(c)) throw error("invalid_surrogate"); else result.append(c); } } throw error("unterminated_string"); }
        void appendEscapedUnicode(StringBuilder result) throws JsonException { char high = unicode(); if (Character.isHighSurrogate(high)) { if (position + 2 > text.length() || text.charAt(position) != '\\' || text.charAt(position + 1) != 'u') throw error("missing_low_surrogate"); position += 2; char low = unicode(); if (!Character.isLowSurrogate(low)) throw error("invalid_low_surrogate"); result.append(high).append(low); } else if (Character.isLowSurrogate(high)) throw error("orphan_low_surrogate"); else result.append(high); }
        char unicode() throws JsonException { if (position + 4 > text.length()) throw error("unicode_escape"); int result = 0; for (int i = 0; i < 4; i++) { int digit = Character.digit(text.charAt(position++), 16); if (digit < 0) throw error("unicode_escape"); result = (result << 4) | digit; } return (char) result; }
        Number number() throws JsonException { int start = position; if (position < text.length() && text.charAt(position) == '-') position++; if (position >= text.length() || !Character.isDigit(text.charAt(position))) throw error("number_expected"); if (text.charAt(position) == '0') { position++; if (position < text.length() && Character.isDigit(text.charAt(position))) throw error("leading_zero"); } else { while (position < text.length() && Character.isDigit(text.charAt(position))) position++; } if (position < text.length() && text.charAt(position) == '.') { position++; int fractionStart = position; while (position < text.length() && Character.isDigit(text.charAt(position))) position++; if (position == fractionStart) throw error("fraction_digit_expected"); } if (position < text.length() && (text.charAt(position) == 'e' || text.charAt(position) == 'E')) { position++; if (position < text.length() && (text.charAt(position) == '+' || text.charAt(position) == '-')) position++; int exponentStart = position; while (position < text.length() && Character.isDigit(text.charAt(position))) position++; if (position == exponentStart) throw error("exponent_digit_expected"); } try { return new BigDecimal(text.substring(start, position)); } catch (NumberFormatException e) { throw error("number_expected"); } }
        boolean take(char expected) { if (position < text.length() && text.charAt(position) == expected) { position++; return true; } return false; }
        JsonException error(String message) { return new JsonException(message + "@" + position); }
    }
}
