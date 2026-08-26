package com.okww.combatagent;

import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.MotionEvent;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Best-effort multi-pointer injector. Every failure is reported to the caller. */
final class TouchController {
    static final int WIDTH = 1280;
    static final int HEIGHT = 720;
    private final Map<Integer, Point> pointers = new ConcurrentHashMap<Integer, Point>();
    private final Object inputManager;
    private final Method inject;
    private volatile long gestureDownTime;

    TouchController() throws Exception {
        InputService service = resolveInputService();
        inputManager = service.manager;
        inject = service.inject;
    }

    private static InputService resolveInputService() throws Exception {
        try {
            return bind("android.hardware.input.InputManagerGlobal");
        } catch (ClassNotFoundException unavailable) {
            return bind("android.hardware.input.InputManager");
        } catch (ReflectiveOperationException unavailable) {
            return bind("android.hardware.input.InputManager");
        }
    }

    private static InputService bind(String className) throws Exception {
        Class<?> managerClass = Class.forName(className);
        Method getInstance = managerClass.getDeclaredMethod("getInstance");
        getInstance.setAccessible(true);
        Object manager = getInstance.invoke(null);
        if (manager == null) throw new IllegalStateException("input_manager_unavailable");
        Method inject = managerClass.getDeclaredMethod("injectInputEvent", InputEvent.class, int.class);
        inject.setAccessible(true);
        return new InputService(manager, inject);
    }

    private static final class InputService {
        final Object manager;
        final Method inject;
        InputService(Object manager, Method inject) {
            this.manager = manager;
            this.inject = inject;
        }
    }

    void down(int pointerId, float x, float y) throws Exception {
        if (pointerId < 0 || pointerId > 31) throw new IllegalArgumentException("invalid_pointer_id");
        if (pointers.containsKey(pointerId)) throw new IllegalStateException("pointer_already_down");
        Point point = new Point(x, y);
        boolean first = pointers.isEmpty();
        if (first) gestureDownTime = SystemClock.uptimeMillis();
        pointers.put(pointerId, point);
        try { inject(MotionEvent.ACTION_DOWN, pointerId); }
        catch (Exception failure) {
            pointers.remove(pointerId);
            if (pointers.isEmpty()) gestureDownTime = 0L;
            releaseAll();
            throw failure;
        }
    }

    void move(int pointerId, float x, float y) throws Exception {
        Point previous = pointers.get(pointerId);
        if (previous == null) throw new IllegalStateException("pointer_not_down");
        pointers.put(pointerId, new Point(x, y));
        try { inject(MotionEvent.ACTION_MOVE, pointerId); }
        catch (Exception failure) { pointers.put(pointerId, previous); releaseAll(); throw failure; }
    }

    void up(int pointerId) throws Exception {
        if (pointers.get(pointerId) == null) return;
        try {
            inject(MotionEvent.ACTION_UP, pointerId);
            pointers.remove(pointerId);
            if (pointers.isEmpty()) gestureDownTime = 0L;
        } catch (Exception failure) {
            pointers.remove(pointerId);
            releaseAll();
            throw failure;
        }
    }

    /** Releases every locally tracked pointer, even when one injection fails. */
    void releaseAll() {
        ArrayList<Integer> ids = new ArrayList<Integer>(pointers.keySet());
        for (Integer id : ids) {
            try { inject(MotionEvent.ACTION_UP, id.intValue()); } catch (Throwable ignored) { }
            pointers.remove(id);
        }
        pointers.clear();
        gestureDownTime = 0L;
    }

    int pointerCount() { return pointers.size(); }

    private void inject(int action, int changedPointer) throws Exception {
        ArrayList<Integer> ids = new ArrayList<Integer>(pointers.keySet());
        if (ids.size() == 0) return;
        java.util.Collections.sort(ids);
        MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[ids.size()];
        MotionEvent.PointerCoords[] coords = new MotionEvent.PointerCoords[ids.size()];
        int actionIndex = 0;
        for (int i = 0; i < ids.size(); i++) {
            int id = ids.get(i).intValue();
            properties[i] = new MotionEvent.PointerProperties();
            properties[i].id = id;
            properties[i].toolType = MotionEvent.TOOL_TYPE_FINGER;
            Point point = pointers.get(id);
            coords[i] = new MotionEvent.PointerCoords();
            coords[i].x = point.x;
            coords[i].y = point.y;
            coords[i].pressure = 1.0f;
            coords[i].size = 1.0f;
            if (id == changedPointer) actionIndex = i;
        }
        int actionCode = action;
        if (action == MotionEvent.ACTION_DOWN && ids.size() > 1) actionCode = MotionEvent.ACTION_POINTER_DOWN | (actionIndex << MotionEvent.ACTION_POINTER_INDEX_SHIFT);
        if (action == MotionEvent.ACTION_UP && ids.size() > 1) actionCode = MotionEvent.ACTION_POINTER_UP | (actionIndex << MotionEvent.ACTION_POINTER_INDEX_SHIFT);
        long now = SystemClock.uptimeMillis();
        long downTime = gestureDownTime == 0L ? now : gestureDownTime;
        MotionEvent event = MotionEvent.obtain(downTime, now, actionCode, ids.size(), properties, coords,
                0, 0, 1.0f, 1.0f, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        try {
            Object result = inject.invoke(inputManager, event, 0 /* INJECT_INPUT_EVENT_MODE_ASYNC */);
            if (result instanceof Boolean && !((Boolean) result).booleanValue()) throw new IllegalStateException("input_injection_rejected");
        } finally { event.recycle(); }
    }

    private static final class Point {
        final float x; final float y;
        Point(float x, float y) {
            if (Float.isNaN(x) || Float.isInfinite(x) || Float.isNaN(y) || Float.isInfinite(y)) throw new IllegalArgumentException("invalid_coordinate");
            this.x = Math.max(0, Math.min(WIDTH - 1, x)); this.y = Math.max(0, Math.min(HEIGHT - 1, y));
        }
    }
}
