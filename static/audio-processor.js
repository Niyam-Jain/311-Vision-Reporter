/**
 * AudioWorklet processor for microphone capture.
 * Runs off the main thread. Converts Float32 PCM → Int16 PCM and
 * accumulates ~100 ms of audio (1600 samples @ 16 kHz) before posting
 * each chunk to the main thread for WebSocket transmission.
 */

const CHUNK_SIZE = 1600; // 100 ms @ 16 kHz

class PCMCaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this._buffer = new Int16Array(CHUNK_SIZE);
        this._filled = 0;
    }

    process(inputs) {
        const input = inputs[0];
        if (!input || !input[0]) return true;

        const samples = input[0]; // Float32Array, one channel

        for (let i = 0; i < samples.length; i++) {
            // Clamp and convert Float32 [-1, 1] → Int16
            const s = Math.max(-1, Math.min(1, samples[i]));
            this._buffer[this._filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;

            if (this._filled === CHUNK_SIZE) {
                // Post a copy — the worklet thread keeps running
                this.port.postMessage(this._buffer.slice(0));
                this._filled = 0;
            }
        }

        return true; // keep processor alive
    }
}

registerProcessor("pcm-capture", PCMCaptureProcessor);
