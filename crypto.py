"""
Blowfish decryption for Deezer streams
"""

import logging
from deemix.utils.crypto import generateBlowfishKey, decryptChunk

logger = logging.getLogger(__name__)


def generate_decrypted(dz, streaming_session, download_url, track_id, start_byte=0, end_byte=None, track_name=None):
    """
    Deezer Blowfish decryption with HTTP Range support:
    - Encrypted stream is split into 2048-byte chunks
    - Every 3rd chunk (0, 3, 6, 9...) is encrypted with Blowfish ECB
    - Other chunks are plain MP3 data
    - Supports byte-range requests for iOS duration calculation
    """
    response = streaming_session.get(download_url, stream=True, timeout=30)
    
    if response.status_code != 200:
        logger.debug(f"✗ Download failed: {response.status_code}")
        return
    
    # Configuration
    decrypt_chunk_size = 2048      # Deezer encryption chunk size (fixed)
    download_chunk_size = 262144   # Download 256KB at a time (increased for better performance)
    yield_size = 131072            # Yield 128KB chunks (increased for better performance)
    
    # Buffers and counters
    chunk_index = 0
    buffer = b''
    output_buffer = bytearray()
    total_decrypted = 0  # Total bytes decrypted from source
    total_yielded = 0    # Total bytes yielded to client
    
    # Range request parameters
    bytes_to_skip = start_byte
    bytes_to_send = (end_byte - start_byte + 1) if end_byte is not None else None
    is_range_request = end_byte is not None
    
    if is_range_request:
        logger.debug(f"Range mode: skip={bytes_to_skip}, send={bytes_to_send}")
    else:
        logger.debug(f"Full stream mode")
    
    # Generate track-specific Blowfish decryption key
    blowfish_key = generateBlowfishKey(str(track_id))
    
    # Stream and decrypt
    for chunk in response.iter_content(chunk_size=download_chunk_size):
        if not chunk:
            break
        
        # Stop early if we've sent all requested bytes
        if bytes_to_send is not None and total_yielded >= bytes_to_send:
            break
        
        buffer += chunk
        
        # Process 2048-byte chunks (Deezer requirement)
        while len(buffer) >= decrypt_chunk_size:
            current_chunk = buffer[:decrypt_chunk_size]
            buffer = buffer[decrypt_chunk_size:]
            
            # Decrypt every 3rd chunk (Deezer encryption pattern)
            if chunk_index % 3 == 0:
                try:
                    decrypted = decryptChunk(blowfish_key, current_chunk)
                    output_buffer.extend(decrypted)
                except Exception as e:
                    logger.debug(f"⚠ Decrypt error chunk {chunk_index}: {e}")
                    output_buffer.extend(current_chunk)
            else:
                output_buffer.extend(current_chunk)
            
            chunk_index += 1
            total_decrypted += decrypt_chunk_size
            
            # Check if we have enough to start yielding
            if len(output_buffer) >= yield_size or (bytes_to_send and len(output_buffer) >= bytes_to_send):
                data_to_yield = bytes(output_buffer)
                
                # Handle byte skipping for range requests
                if bytes_to_skip > 0:
                    if len(data_to_yield) <= bytes_to_skip:
                        # Skip entire chunk
                        bytes_to_skip -= len(data_to_yield)
                        output_buffer = bytearray()
                        continue
                    else:
                        # Skip partial chunk
                        data_to_yield = data_to_yield[bytes_to_skip:]
                        bytes_to_skip = 0
                
                # Trim to requested size if needed
                if bytes_to_send is not None:
                    remaining = bytes_to_send - total_yielded
                    if len(data_to_yield) > remaining:
                        data_to_yield = data_to_yield[:remaining]
                
                # Yield data
                if data_to_yield:
                    yield data_to_yield
                    total_yielded += len(data_to_yield)
                
                output_buffer = bytearray()
                
                # Stop if we've sent everything
                if bytes_to_send is not None and total_yielded >= bytes_to_send:
                    break
    
    # Flush remaining DECRYPTED data only (ignore incomplete buffer < 2048 bytes)
    # DO NOT add incomplete buffer to avoid corrupting MP3 for Android
    if output_buffer:
        data_to_yield = bytes(output_buffer)
        
        # Handle remaining skips
        if bytes_to_skip > 0:
            if len(data_to_yield) > bytes_to_skip:
                data_to_yield = data_to_yield[bytes_to_skip:]
            else:
                data_to_yield = b''
        
        # Trim to requested size
        if bytes_to_send is not None and data_to_yield:
            remaining = bytes_to_send - total_yielded
            if len(data_to_yield) > remaining:
                data_to_yield = data_to_yield[:remaining]
        
        if data_to_yield:
            yield data_to_yield
            total_yielded += len(data_to_yield)
    
    # Log completion
    logger.debug(f"Streamed {chunk_index} chunks (decrypted={total_decrypted}, yielded={total_yielded})")
