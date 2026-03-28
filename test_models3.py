import onnxruntime as ort
import numpy as np

# Load models
mel_session = ort.InferenceSession('frontend/public/models/melspectrogram.onnx')

# Test with more audio to get more frames
audio = np.random.randn(1, 16000).astype(np.float32)  # 1 second at 16kHz
mel_out = mel_session.run(None, {'input': audio})
print(f'Mel output shape: {mel_out[0].shape}')
print(f'Mel frames: {mel_out[0].shape[0]}, features per frame: {mel_out[0].shape[3]}')

# The output shape is [time, 1, 1, 32]
# For embedding model we need [1, 76, 32, 1]
