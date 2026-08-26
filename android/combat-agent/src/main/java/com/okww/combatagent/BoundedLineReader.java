package com.okww.combatagent;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;

/** Reads exactly one bounded UTF-8 JSON line without allowing unbounded buffering. */
final class BoundedLineReader {
    private final InputStream input;
    private final int maxBytes;

    BoundedLineReader(InputStream input, int maxBytes) {
        if (input == null || maxBytes <= 0) throw new IllegalArgumentException("invalid_reader");
        this.input = input;
        this.maxBytes = maxBytes;
    }

    String readFrame() throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(Math.min(maxBytes, 4096));
        boolean sawByte = false;
        while (true) {
            int value = input.read();
            if (value < 0) {
                if (!sawByte) return null;
                break;
            }
            sawByte = true;
            if (value == '\n') break;
            if (bytes.size() >= maxBytes) throw new FrameTooLargeException();
            bytes.write(value);
        }
        byte[] frame = bytes.toByteArray();
        int length = frame.length;
        if (length > 0 && frame[length - 1] == '\r') length--;
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(frame, 0, length)).toString();
        } catch (CharacterCodingException error) {
            throw new InvalidUtf8Exception(error);
        }
    }

    static final class FrameTooLargeException extends IOException { FrameTooLargeException() { super("frame_too_large"); } }
    static final class InvalidUtf8Exception extends IOException { InvalidUtf8Exception(Throwable cause) { super("invalid_utf8", cause); } }
}
