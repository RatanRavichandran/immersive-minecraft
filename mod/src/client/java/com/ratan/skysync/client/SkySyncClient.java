package com.ratan.skysync.client;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.client.world.ClientWorld;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Vec3d;
import net.minecraft.world.LightType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

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

			// Both are null on the title screen and during world load
			// (PLAN.md section 6) — skip silently rather than throw,
			// since this is the normal state every tick until a world
			// is actually loaded.
			ClientWorld world = client.world;
			ClientPlayerEntity player = client.player;
			if (world == null || player == null) {
				return;
			}

			send(telemetryPayload(world, player));
		} catch (Throwable t) {
			LOGGER.warn("[SkySync] tick handler failed, skipping this send", t);
		}
	}

	/**
	 * The wire protocol from PLAN.md section 6: one JSON object, full state
	 * every time, no deltas. {@code skyLight}/{@code blockLight}/{@code y}
	 * are read at the player's own block position — that position is what
	 * makes skyLight a clean "is there a path to the sky from where I am"
	 * signal rather than a scene-wide average.
	 */
	private String telemetryPayload(ClientWorld world, ClientPlayerEntity player) {
		BlockPos pos = player.getBlockPos();

		long tick = Math.floorMod(world.getTimeOfDay(), 24000L);
		float rain = world.getRainGradient(1.0f);
		float thunder = world.getThunderGradient(1.0f);
		int lightning = world.getLightningTicksLeft();
		int skyLight = world.getLightLevel(LightType.SKY, pos);
		int blockLight = world.getLightLevel(LightType.BLOCK, pos);
		int y = pos.getY();
		int skyColor = packSkyColor(world.getSkyColor(player.getPos(), 1.0f));
		// namespace:path, e.g. "minecraft:overworld" — exactly PLAN.md's
		// example. Dimension identifiers can't contain a '"', so this
		// never needs real JSON string escaping.
		String dimension = world.getRegistryKey().getValue().toString();

		return String.format(
				Locale.ROOT,
				"{\"tick\":%d,\"rain\":%s,\"thunder\":%s,\"lightning\":%d,"
						+ "\"skyLight\":%d,\"blockLight\":%d,\"y\":%d,\"skyColor\":%d,"
						+ "\"dimension\":\"%s\"}",
				tick, rain, thunder, lightning,
				skyLight, blockLight, y, skyColor,
				dimension
		);
	}

	/** Vec3d components are 0.0-1.0 per channel; pack into 0xRRGGBB. */
	private static int packSkyColor(Vec3d color) {
		int r = clampToByte(color.x);
		int g = clampToByte(color.y);
		int b = clampToByte(color.z);
		return (r << 16) | (g << 8) | b;
	}

	private static int clampToByte(double channel) {
		int value = Math.round((float) (channel * 255.0));
		return Math.max(0, Math.min(255, value));
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
