package com.okww.combatagent;

/** app_process entry point: app_process -Djava.class.path=... / com.okww.combatagent.Main ... */
public final class Main {
    public static void main(String[] args) {
        String normal = null;
        String emergency = null;
        String buildVersion = "unknown";
        boolean normalSeen = false;
        boolean emergencySeen = false;
        boolean buildVersionSeen = false;
        try {
            for (int i = 0; i < args.length; i++) {
                if ("--normal-socket".equals(args[i])) {
                    if (normalSeen || i + 1 >= args.length) throw new IllegalArgumentException("normal_socket_must_be_provided_once");
                    normal = args[++i]; normalSeen = true;
                } else if ("--emergency-socket".equals(args[i])) {
                    if (emergencySeen || i + 1 >= args.length) throw new IllegalArgumentException("emergency_socket_must_be_provided_once");
                    emergency = args[++i]; emergencySeen = true;
                } else if ("--build-version".equals(args[i])) {
                    if (buildVersionSeen || i + 1 >= args.length) throw new IllegalArgumentException("build_version_must_be_provided_once");
                    buildVersion = args[++i]; buildVersionSeen = true;
                } else throw new IllegalArgumentException("unknown_argument");
            }
            if (!normalSeen || !emergencySeen) throw new IllegalArgumentException("both_socket_names_are_required");
            AgentServer.validateSocketName(normal); AgentServer.validateSocketName(emergency); AgentServer.validateBuildVersion(buildVersion);
            final TouchController controller = new TouchController();
            final TouchScheduler scheduler = new TouchScheduler(controller);
            final AgentServer server = new AgentServer(normal, emergency, buildVersion, scheduler);
            Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() { public void run() { server.close(); scheduler.shutdown(); } }, "okww-shutdown"));
            server.start();
            while (true) Thread.sleep(1000L);
        } catch (Throwable error) {
            // Keep app_process failure observable without attempting unsafe input.
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
