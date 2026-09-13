package com.ratan.skysync.client;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.MinecraftClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

/**
 * Client-only entrypoint. Reads nothing yet (see Task 1.3 / PLAN.md section 6)
 * — this stage only proves the transport: every {@link #TICKS_PER_SEND} ticks,
 * fire a fixed placeholder JSON datagram at the bridge on localhost.
 *
 * <p>The mod is deliberately dumb. All modelling, easing, and calibration
 * live in the Python bridge, so tuning never requires a Minecraft restart
 * (PLAN.md section 4). This class must never crash or stall the render
 * thread — a lighting toy is not worth a client crash.
 */
public class SkySyncClient implements ClientModInitializer {
	public static final String MOD_ID = "skysync";
	private static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

	private static final InetSocketAddress BRIDGE_ADDRESS =
			new InetSocketAddress(InetAddress.getLoopbackAddress(), 25566);
	private static final int TICKS_PER_SEND = 10;

	// Created lazily on first send and reused for the life of the client —
	// never opened per-packet.
	private DatagramSocket socket;
	private int tickCounter = 0;

	@Override
	public void onInitializeClient() {
		LOGGER.info("[SkySync] initialized, will emit UDP telemetry to {} every {} ticks",
				BRIDGE_ADDRESS, TICKS_PER_SEND);

		ClientTickEvents.END_CLIENT_TICK.register(this::onEndTick);
	}

	private void onEndTick(MinecraftClient client) {
		// Catch-everything by design (PLAN.md section 6 / 11): a socket
		// failure or an NPE here must never take the game down with it.
		try {
			tickCounter++;
			if (tickCounter < TICKS_PER_SEND) {
				return;
			}
			tickCounter = 0;

			send(placeholderPayload());
		} catch (Throwable t) {
			LOGGER.warn("[SkySync] tick handler failed, skipping this send", t);
		}
	}

	private String placeholderPayload() {
		// M2 placeholder only, isolates the transport from the modelling
		// work. Task 1.3 replaces this with the real fields from PLAN.md
		// section 6: tick, rain, thunder, lightning, skyLight, blockLight,
		// y, skyColor, dimension.
		return "{\"placeholder\":true,\"nanos\":" + System.nanoTime() + "}";
	}

	private void send(String json) {
		try {
			if (socket == null) {
				socket = new DatagramSocket();
			}
			byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
			socket.send(new DatagramPacket(bytes, bytes.length, BRIDGE_ADDRESS));
		} catch (IOException e) {
			LOGGER.warn("[SkySync] failed to send UDP packet to bridge", e);
		}
	}
}
