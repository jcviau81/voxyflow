# Check the actual output format
import onnxruntime as ort
import numpy as np

mel_session = ort.InferenceSession('frontend/public/models/melspectrogram.onnx')
audio = np.random.randn(1, 1280).astype(np.float32)
mel_out = mel_session.run(None, {'input': audio})

print(f'Mel output key: {list(mel_out)}')
print(f'Mel output shape: {mel_out[0].shape}')
print(f'Total elements: {mel_out[0].size}')
print(f'Flattened shape would be: {mel_out[0].flatten().shape}')

# The output is [time, 1, 1, 32]
# So for 1280 samples we get [1, 1, 5, 32]
# This means 1 batch, 1 channel, 5 time frames, 32 features each
# When flattened, this is 160 elements total

# But the code expects frames of 32 features each
# So we should reshape to [5, 32] not treat as [160]
