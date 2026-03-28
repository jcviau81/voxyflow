class AudioProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.bufferSize = options.processorOptions?.bufferSize || 512;
    this.buffer = [];
  }

  process(inputs, outputs) {
    const input = inputs[0];
    if (input && input[0]) {
      const samples = input[0];
      for (let i = 0; i < samples.length; i++) {
        this.buffer.push(samples[i]);
        if (this.buffer.length >= this.bufferSize) {
          this.port.postMessage({ 
            audio: new Float32Array(this.buffer.slice(0, this.bufferSize)) 
          });
          this.buffer = this.buffer.slice(this.bufferSize);
        }
      }
    }
    return true;
  }
}

registerProcessor('audio-processor', AudioProcessor);
