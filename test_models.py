import onnxruntime as ort
import numpy as np

# Load models
mel_session = ort.InferenceSession('frontend/public/models/melspectrogram.onnx')
emb_session = ort.InferenceSession('frontend/public/models/embedding_model.onnx')
ww_session = ort.InferenceSession('frontend/public/models/alexa_v0.1.onnx')

# Print model info
print('Melspectrogram model:')
for inp in mel_session.get_inputs():
    print(f'  Input: {inp.name}, shape: {inp.shape}')
for out in mel_session.get_outputs():
    print(f'  Output: {out.name}, shape: {out.shape}')

print('\nEmbedding model:')
for inp in emb_session.get_inputs():
    print(f'  Input: {inp.name}, shape: {inp.shape}')
for out in emb_session.get_outputs():
    print(f'  Output: {out.name}, shape: {out.shape}')

print('\nWake word model:')
for inp in ww_session.get_inputs():
    print(f'  Input: {inp.name}, shape: {inp.shape}')
for out in ww_session.get_outputs():
    print(f'  Output: {out.name}, shape: {out.shape}')

# Test with dummy data
audio = np.random.randn(1280).astype(np.float32)
mel_out = mel_session.run(None, {'input': audio})
print(f'\nMel output shape: {mel_out[0].shape}')
print(f'Mel output data shape: {mel_out[0].flatten().shape}')
