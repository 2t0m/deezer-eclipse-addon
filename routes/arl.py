"""
ARL management route - Manual ARL refresh endpoint
"""

from flask import jsonify
from helpers import validate_token


def register_arl_route(app, API_KEY, dz, arl_manager_factory):
    """Register ARL management route"""
    
    @app.route('/<token>/arl/refresh', methods=['POST', 'GET'])
    def refresh_arl(token):
        """Manually trigger ARL refresh"""
        
        # Validate token
        if not validate_token(token, API_KEY):
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Check if ARL manager is available
        arl_manager = arl_manager_factory()
        if not arl_manager:
            return jsonify({
                'error': 'ARL auto-refresh not configured',
                'message': 'Please set DEEZER_EMAIL and DEEZER_PASSWORD in .env'
            }), 503
        
        # Try to get a new ARL
        print("🔄 Manual ARL refresh requested", flush=True)
        new_arl = arl_manager.get_new_arl()
        
        if new_arl:
            # Test the new ARL
            if dz.login_via_arl(new_arl):
                arl_manager.save_arl_to_env(new_arl)
                return jsonify({
                    'success': True,
                    'message': 'ARL refreshed successfully',
                    'arl_preview': f"{new_arl[:20]}...",
                    'timestamp': __import__('datetime').datetime.now().isoformat()
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'error': 'New ARL failed authentication'
                }), 500
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to retrieve new ARL'
            }), 500
    
    @app.route('/<token>/arl/status', methods=['GET'])
    def arl_status(token):
        """Check ARL status"""
        
        # Validate token
        if not validate_token(token, API_KEY):
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Check if logged in
        try:
            # Try to get user info to verify ARL is working
            user_info = dz.gw.get_user_data()
            if user_info:
                return jsonify({
                    'status': 'valid',
                    'user_id': user_info.get('USER_ID'),
                    'user_name': user_info.get('BLOG_NAME'),
                    'auto_refresh_available': arl_manager_factory() is not None
                }), 200
            else:
                return jsonify({
                    'status': 'invalid',
                    'auto_refresh_available': arl_manager_factory() is not None
                }), 200
        except:
            return jsonify({
                'status': 'invalid',
                'auto_refresh_available': arl_manager_factory() is not None
            }), 200
