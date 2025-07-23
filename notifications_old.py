async def _send_slack_notification_safe(self, notification: NotificationItem):
        """Safe wrapper for Slack notifications"""
        try:
            await self._send_slack_notification(notification)
            self.rate_limits['slack']['current'] += 1
            self.delivery_stats['slack']['sent'] += 1
        except Exception as e:
            self.delivery_stats['slack']['failed'] += 1
            if notification.retry_count > 0:
                self.delivery_stats['slack']['retries'] += 1
            raise e

async def _send_slack_notification(self, notification: NotificationItem):
    """
    Send Slack notification with blocks and rich formatting
    """
    slack_config = self.config.get('slack', {})
    webhook_url = slack_config.get('webhook_url')
    
    if not webhook_url:
        raise Exception("Slack webhook URL not configured")
        
    start_time = time.time()
    
    try:
        template = notification.template
        title = notification.title
        message = notification.message
        data = notification.data
        
        # Create Slack blocks
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{template['emoji']} {title}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            }
        ]
        
        # Add priority indicator
        priority_colors = {
            NotificationPriority.LOW: "good",
            NotificationPriority.MEDIUM: "warning",
            NotificationPriority.HIGH: "danger",
            NotificationPriority.CRITICAL: "danger"
        }
        
        # Add data fields
        if data:
            fields = []
            for key, value in data.items():
                if key in ['timestamp', 'analysis_timestamp']:
                    continue
                    
                field_value = str(value)
                if isinstance(value, (int, float)):
                    if 'usd' in key.lower():
                        field_value = f"${value:,.2f}"
                    elif 'confidence' in key.lower() or 'score' in key.lower():
                        field_value = f"{value:.1%}"
                        
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*{self._format_field_name(key)}:*\n{field_value}"
                })
            
            if fields:
                blocks.append({
                    "type": "section",
                    "fields": fields[:10]  # Slack limits to 10 fields
                })
        
        # Add action buttons
        if data.get('token_address'):
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "📊 View on DexScreener"
                        },
                        "url": f"https://dexscreener.com/solana/{data['token_address']}"
                    }
                ]
            })
        
        # Add timestamp and retry info
        context_elements = [
            {
                "type": "mrkdwn",
                "text": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            }
        ]
        
        if notification.retry_count > 0:
            context_elements.append({
                "type": "mrkdwn", 
                "text": f"🔄 Retry {notification.retry_count}/{notification.max_retries}"
            })
        
        blocks.append({
            "type": "context",
            "elements": context_elements
        })
        
        payload = {
            "blocks": blocks,
            "attachments": [
                {
                    "color": priority_colors.get(notification.priority, "good"),
                    "fallback": f"{title}: {message}"
                }
            ]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10) as response:
                response.raise_for_status()
        
        delivery_time = time.time() - start_time
        
        self._log_notification_delivery(
            notification.id, notification.notification_type, 'slack', 'webhook',
            title, message, 'sent', delivery_time, notification.retry_count
        )
        
        if self.advanced_logger:
            self.advanced_logger.log_notification_sent('notifications', 
                                                        notification.notification_type, 
                                                        'slack', True,
                                                        f'Delivered in {delivery_time:.3f}s')
        
    except Exception as e:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'slack_send_error', 
                                            f'❌ Slack notification failed: {e}')
        raise

async def _send_webhook_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for custom webhook notifications"""
    try:
        await self._send_webhook_notification(notification)
        self.delivery_stats['webhook']['sent'] += 1
    except Exception as e:
        self.delivery_stats['webhook']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['webhook']['retries'] += 1
        raise e

async def _send_webhook_notification(self, notification: NotificationItem):
    """Send custom webhook notification"""
    webhook_config = self.config.get('webhook', {})
    webhook_urls = webhook_config.get('urls', [])
    
    if not webhook_urls:
        raise Exception("No webhook URLs configured")
    
    start_time = time.time()
    
    payload = {
        "notification_id": notification.id,
        "type": notification.notification_type,
        "title": notification.title,
        "message": notification.message,
        "data": notification.data,
        "priority": notification.priority.value,
        "retry_count": notification.retry_count,
        "timestamp": datetime.now().isoformat()
    }
    
    for webhook_url in webhook_urls:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url, 
                    json=payload, 
                    timeout=10,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    response.raise_for_status()
            
            delivery_time = time.time() - start_time
            
            self._log_notification_delivery(
                notification.id, notification.notification_type, 'webhook', webhook_url,
                notification.title, notification.message, 'sent', delivery_time, notification.retry_count
            )
            
        except Exception as e:
            self.logger.error(f"Failed to send webhook notification to {webhook_url}: {e}")
            self._log_notification_delivery(
                notification.id, notification.notification_type, 'webhook', webhook_url,
                notification.title, notification.message, 'failed', 0, notification.retry_count, str(e)
            )
            raise e

async def _send_push_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for push notifications"""
    try:
        await self._send_push_notification(notification)
        self.delivery_stats['push']['sent'] += 1
    except Exception as e:
        self.delivery_stats['push']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['push']['retries'] += 1
        raise e

async def _send_push_notification(self, notification: NotificationItem):
    """Send push notification via Pushbullet or similar service"""
    push_config = self.config.get('push', {})
    service = push_config.get('service', 'pushbullet')
    
    if service == 'pushbullet':
        await self._send_pushbullet_notification(notification, push_config)
    elif service == 'ntfy':
        await self._send_ntfy_notification(notification, push_config)
    else:
        raise Exception(f"Unsupported push service: {service}")

async def _send_pushbullet_notification(self, notification: NotificationItem, config):
    """Send notification via Pushbullet"""
    api_key = config.get('api_key')
    if not api_key:
        raise Exception("Pushbullet API key not configured")
    
    start_time = time.time()
    
    payload = {
        "type": "note",
        "title": f"{notification.template['emoji']} {notification.title}",
        "body": notification.message
    }
    
    headers = {
        "Access-Token": api_key,
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.pushbullet.com/v2/pushes",
            json=payload,
            headers=headers,
            timeout=10
        ) as response:
            response.raise_for_status()
    
    delivery_time = time.time() - start_time
    
    self._log_notification_delivery(
        notification.id, notification.notification_type, 'push', 'pushbullet',
        notification.title, notification.message, 'sent', delivery_time, notification.retry_count
    )

async def _send_ntfy_notification(self, notification: NotificationItem, config):
    """Send notification via ntfy.sh"""
    topic = config.get('topic')
    if not topic:
        raise Exception("ntfy topic not configured")
    
    start_time = time.time()
    
    headers = {
        "Title": f"{notification.template['emoji']} {notification.title}",
        "Priority": self._get_ntfy_priority(notification.priority),
        "Tags": self._get_ntfy_tags(notification.notification_type)
    }
    
    url = f"https://ntfy.sh/{topic}"
    if config.get('server'):
        url = f"{config['server']}/{topic}"
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            data=notification.message,
            headers=headers,
            timeout=10
        ) as response:
            response.raise_for_status()
    
    delivery_time = time.time() - start_time
    
    self._log_notification_delivery(
        notification.id, notification.notification_type, 'push', 'ntfy',
        notification.title, notification.message, 'sent', delivery_time, notification.retry_count
    )

def _get_ntfy_priority(self, priority: NotificationPriority) -> str:
    """Convert notification priority to ntfy priority"""
    mapping = {
        NotificationPriority.LOW: "2",
        NotificationPriority.MEDIUM: "3",
        NotificationPriority.HIGH: "4",
        NotificationPriority.CRITICAL: "5"
    }
    return mapping.get(priority, "3")

def _get_ntfy_tags(self, notification_type: str) -> str:
    """Get appropriate tags for ntfy notification"""
    tag_mapping = {
        'rug_alert': 'warning,skull',
        'pump_alert': 'rocket,money',
        'fake_volume_alert': 'chart,warning',
        'bundle_alert': 'package,warning',
        'rugcheck_failed': 'shield,warning',
        'trade_notification': 'money,check',
        'system_status': 'robot,info',
        'error_alert': 'boom,warning',
        'performance_alert': 'zap,warning'
    }
    return tag_mapping.get(notification_type, 'info')

def _create_html_email(self, notification: NotificationItem):
    """Create rich HTML email template"""
    template = notification.template
    title = notification.title
    message = notification.message
    data = notification.data
    
    # Color based on priority
    priority_colors = {
        NotificationPriority.LOW: "#e6f3ff",
        NotificationPriority.MEDIUM: "#fff2e6", 
        NotificationPriority.HIGH: "#ffe6e6",
        NotificationPriority.CRITICAL: "#ff4444"
    }
    
    bg_color = priority_colors.get(notification.priority, "#f8f9fa")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>DexScreener Bot Alert</title>
        <style>
            .priority-indicator {{
                display: inline-block;
                padding: 4px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                background-color: {template.get('color', '#666')};
            }}
            .retry-info {{
                background-color: #fff3cd;
                border: 1px solid #ffeaa7;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
            }}
        </style>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: {bg_color}; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0; font-size: 24px;">{template['emoji']} {title}</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">DexScreener Solana Bot</p>
                <span class="priority-indicator">{notification.priority.value.upper()}</span>
            </div>
            
            <div style="padding: 20px;">
                <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px;">{message}</p>
                
                {f'<div class="retry-info"><strong>⚠️ Retry Attempt:</strong> {notification.retry_count}/{notification.max_retries}</div>' if notification.retry_count > 0 else ''}
                
                {"<h3>Details:</h3>" if data else ""}
                <table style="width: 100%; border-collapse: collapse;">
    """
    
    # Add data rows
    if data:
        for key, value in data.items():
            if key in ['timestamp', 'analysis_timestamp']:
                continue
                
            formatted_value = str(value)
            if isinstance(value, (int, float)):
                if 'usd' in key.lower():
                    formatted_value = f"${value:,.2f}"
                elif 'confidence' in key.lower() or 'score' in key.lower():
                    formatted_value = f"{value:.1%}"
                    
            html += f"""
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">{self._format_field_name(key)}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">{formatted_value}</td>
                </tr>
            """
    
    html += f"""
                </table>
                
                <div style="margin-top: 30px; padding: 15px; background-color: #f8f9fa; border-radius: 5px; text-align: center;">
                    <p style="margin: 0; color: #666; font-size: 14px;">
                        🕐 Sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}<br>
                        Generated by DexScreener Solana Bot<br>
                        Notification ID: {notification.id}
                    </p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

def _format_field_name(self, field_name):
    """Format field names for display"""
    return field_name.replace('_', ' ').title()

def _log_notification_delivery(self, notification_id, notification_type, platform, recipient, 
                                title, message, status, delivery_time, retry_count=0, error_message=None):
    """Log notification delivery to database"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        # Create data hash for deduplication
        data_content = f"{notification_type}:{title}:{message}"
        data_hash = hashlib.md5(data_content.encode()).hexdigest()
        
        cursor.execute('''
            INSERT OR REPLACE INTO notification_log 
            (notification_id, notification_type, platform, recipient, title, message, status, 
                sent_at, delivery_time, retry_count, error_message, priority, data_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            notification_id, notification_type, platform, recipient, title, message[:500], status,
            int(time.time()), delivery_time, retry_count, error_message, 'medium', data_hash
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        self.logger.error(f"Error logging notification delivery: {e}")

async def send_alert_notification(self, alert_type, symbol, confidence, indicators, additional_data=None):
    """
    Send alert notification with standardized formatting
    
    Wrapper function for common alert types
    """
    template = self.templates.get(f"{alert_type}_alert", self.templates['system_status'])
    
    # Create message based on alert type
    if alert_type == 'rug':
        message = f"⚠️ Potential rug pull detected for *{symbol}* with {confidence:.1%} confidence"
    elif alert_type == 'pump':
        message = f"📈 Price pump detected for *{symbol}* with {confidence:.1%} confidence"
    elif alert_type == 'fake_volume':
        message = f"🎭 Fake volume detected for *{symbol}* with score {confidence:.3f}"
    elif alert_type == 'bundle':
        message = f"📦 Bundle launch detected for *{symbol}* with {confidence:.1%} confidence"
    elif alert_type == 'rugcheck_failed':
        message = f"🔒 RugCheck verification failed for *{symbol}*"
    else:
        message = f"Alert detected for *{symbol}*"
    
    # Add indicators
    if indicators:
        message += f"\n\n🔍 *Key Indicators:*"
        for indicator in indicators[:3]:  # Show top 3 indicators
            message += f"\n• {indicator}"
    
    # Combine with additional data
    notification_data = {'symbol': symbol, 'confidence': confidence}
    if additional_data:
        notification_data.update(additional_data)
        
    await self.send_notification(
        f'{alert_type}_alert',
        template['title'].format(symbol=symbol),
        message,
        notification_data,
        template['priority'].value
    )

async def send_system_notification(self, title, message, data=None, priority='low'):
    """Send system status notification"""
    await self.send_notification('system_status', title, message, data, priority)

async def send_trade_notification(self, action, symbol, amount, data=None):
    """Send trading notification"""
    title = f"💰 {action.upper()} ORDER: {symbol}"
    message = f"Trade executed: {action} {amount} SOL of {symbol}"
    
    await self.send_notification('trade_notification', title, message, data, 'medium')

async def send_error_notification(self, error_type, error_message, data=None):
    """Send error notification"""
    title = f"💥 SYSTEM ERROR: {error_type}"
    message = f"Error detected: {error_message}"
    
    await self.send_notification('error_alert', title, message, data, 'critical')

async def send_performance_alert(self, metric, value, threshold, data=None):
    """Send performance alert"""
    title = f"⚡ PERFORMANCE ALERT: {metric}"
    message = f"Metric {metric} is {value}, exceeding threshold of {threshold}"
    
    await self.send_notification('performance_alert', title, message, data, 'medium')

def get_stats(self):
    """Get comprehensive notification statistics"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        # Get today's stats
        today = datetime.now().strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT platform, notification_type, COUNT(*) as count, 
                    AVG(delivery_time) as avg_time, status
            FROM notification_log 
            WHERE date(sent_at, 'unixepoch') = ?
            GROUP BY platform, notification_type, status
        ''', (today,))
        
        daily_stats = cursor.fetchall()
        
        # Get overall stats
        cursor.execute('''
            SELECT platform, COUNT(*) as total, 
                    SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    AVG(delivery_time) as avg_delivery_time
            FROM notification_log 
            GROUP BY platform
        ''')
        
        overall_stats = cursor.fetchall()
        
        # Get recent failed notifications
        cursor.execute('''
            SELECT notification_type, platform, error_message, sent_at
            FROM notification_log 
            WHERE status = 'failed' AND sent_at > ?
            ORDER BY sent_at DESC
            LIMIT 10
        ''', (int(time.time()) - 3600,))  # Last hour
        
        recent_failures = cursor.fetchall()
        
        # Get retry statistics
        cursor.execute('''
            SELECT platform, AVG(retry_count) as avg_retries, 
                    MAX(retry_count) as max_retries
            FROM notification_log 
            WHERE retry_count > 0
            GROUP BY platform
        ''')
        
        retry_stats = cursor.fetchall()
        
        conn.close()
        
        return {
            'daily_stats': [dict(zip(['platform', 'type', 'count', 'avg_time', 'status'], row)) 
                            for row in daily_stats],
            'overall_stats': [dict(zip(['platform', 'total', 'sent', 'failed', 'avg_delivery_time'], row)) 
                                for row in overall_stats],
            'recent_failures': [dict(zip(['type', 'platform', 'error', 'timestamp'], row)) 
                                for row in recent_failures],
            'retry_stats': [dict(zip(['platform', 'avg_retries', 'max_retries'], row)) 
                            for row in retry_stats],
            'current_stats': self.delivery_stats,
            'queue_size': self.notification_queue.qsize(),
            'is_processing': self.is_processing
        }
        
    except Exception as e:
        self.logger.error(f"Error getting notification stats: {e}")
        return {
            'error': str(e),
            'current_stats': self.delivery_stats,
            'queue_size': self.notification_queue.qsize(),
            'is_processing': self.is_processing
        }

def get_delivery_health(self):
    """Get delivery health metrics"""
    stats = self.get_stats()
    health_score = 100
    issues = []
    
    # Check overall delivery success rate
    for platform_stats in stats.get('overall_stats', []):
        platform = platform_stats['platform']
        total = platform_stats['total']
        sent = platform_stats['sent']
        
        if total > 0:
            success_rate = sent / total
            if success_rate < 0.9:  # Less than 90% success
                health_score -= 15
                issues.append(f"{platform} has low success rate: {success_rate:.1%}")
            elif success_rate < 0.95:  # Less than 95% success
                health_score -= 5
                issues.append(f"{platform} has moderate success rate: {success_rate:.1%}")
    
    # Check recent failures
    recent_failures = len(stats.get('recent_failures', []))
    if recent_failures > 10:
        health_score -= 20
        issues.append(f"High number of recent failures: {recent_failures}")
    elif recent_failures > 5:
        health_score -= 10
        issues.append(f"Moderate number of recent failures: {recent_failures}")
    
    # Check queue size
    queue_size = stats.get('queue_size', 0)
    if queue_size > 100:
        health_score -= 15
        issues.append(f"Large queue backlog: {queue_size} notifications")
    elif queue_size > 50:
        health_score -= 5
        issues.append(f"Moderate queue backlog: {queue_size} notifications")
    
    # Determine health status
    if health_score >= 90:
        status = "EXCELLENT"
    elif health_score >= 75:
        status = "GOOD"
    elif health_score >= 60:
        status = "FAIR"
    elif health_score >= 40:
        status = "POOR"
    else:
        status = "CRITICAL"
    
    return {
        'health_score': max(0, health_score),
        'status': status,
        'issues': issues,
        'recommendations': self._get_health_recommendations(issues)
    }

def _get_health_recommendations(self, issues):
    """Get recommendations based on health issues"""
    recommendations = []
    
    for issue in issues:
        if 'success rate' in issue:
            recommendations.append("Check platform configurations and API credentials")
        elif 'failures' in issue:
            recommendations.append("Review error logs and increase retry limits")
        elif 'queue backlog' in issue:
            recommendations.append("Consider increasing concurrent workers or optimizing delivery")
    
    if not recommendations:
        recommendations.append("System is operating normally")
    
    return recommendations

async def test_connectivity(self):
    """Test connectivity to all configured notification platforms"""
    test_results = {}
    
    # Test Telegram
    if self.config.get('telegram', {}).get('enabled'):
        try:
            if self.telegram_bot:
                bot_info = await self.telegram_bot.get_me()
                test_results['telegram'] = {'status': 'success', 'bot_name': bot_info.first_name}
            else:
                test_results['telegram'] = {'status': 'failed', 'error': 'Bot not initialized'}
        except Exception as e:
            test_results['telegram'] = {'status': 'failed', 'error': str(e)}
    
    # Test Discord
    if self.config.get('discord', {}).get('enabled'):
        try:
            webhook_url = self.config['discord']['webhook_url']
            async with aiohttp.ClientSession() as session:
                test_payload = {"content": "🧪 Connectivity test"}
                async with session.post(webhook_url, json=test_payload, timeout=5) as response:
                    if response.status == 204:
                        test_results['discord'] = {'status': 'success'}
                    else:
                        test_results['discord'] = {'status': 'failed', 'error': f'HTTP {response.status}'}
        except Exception as e:
            test_results['discord'] = {'status': 'failed', 'error': str(e)}
    
    # Test Email
    if self.config.get('email', {}).get('enabled'):
        try:
            email_config = self.config['email']
            server = smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port'])
            server.starttls()
            server.login(email_config['username'], email_config['password'])
            server.quit()
            test_results['email'] = {'status': 'success'}
        except Exception as e:
            test_results['email'] = {'status': 'failed', 'error': str(e)}
    
    # Test Slack
    if self.config.get('slack', {}).get('enabled'):
        try:
            webhook_url = self.config['slack']['webhook_url']
            async with aiohttp.ClientSession() as session:
                test_payload = {"text": "🧪 Connectivity test"}
                async with session.post(webhook_url, json=test_payload, timeout=5) as response:
                    if response.status == 200:
                        test_results['slack'] = {'status': 'success'}
                    else:
                        test_results['slack'] = {'status': 'failed', 'error': f'HTTP {response.status}'}
        except Exception as e:
            test_results['slack'] = {'status': 'failed', 'error': str(e)}
    
    return test_results

def cleanup_old_logs(self, days_to_keep=30):
    """Clean up old notification logs"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        cutoff_timestamp = int(time.time()) - (days_to_keep * 24 * 3600)
        
        cursor.execute('DELETE FROM notification_log WHERE sent_at < ?', (cutoff_timestamp,))
        deleted_count = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'cleanup_logs', 
                                            f'Cleaned up {deleted_count} old notification logs')
        
        return deleted_count
        
    except Exception as e:
        self.logger.error(f"Error cleaning up notification logs: {e}")
        return 0

def export_notification_data(self, start_date=None, end_date=None, format='json'):
    """Export notification data for analysis"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        query = 'SELECT * FROM notification_log'
        params = []
        
        if start_date or end_date:
            conditions = []
            if start_date:
                conditions.append('sent_at >= ?')
                params.append(int(start_date.timestamp()))
            if end_date:
                conditions.append('sent_at <= ?')
                params.append(int(end_date.timestamp()))
            
            query += ' WHERE ' + ' AND '.join(conditions)
        
        query += ' ORDER BY sent_at DESC'
        
        cursor.execute(query, params)
        data = cursor.fetchall()
        
        # Get column names
        column_names = [description[0] for description in cursor.description]
        
        conn.close()
        
        if format.lower() == 'json':
            export_data = []
            for row in data:
                row_dict = dict(zip(column_names, row))
                # Convert timestamp to readable format
                if row_dict['sent_at']:
                    row_dict['sent_at_readable'] = datetime.fromtimestamp(row_dict['sent_at']).isoformat()
                export_data.append(row_dict)
            
            filename = f"notifications_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump({
                    'export_timestamp': datetime.now().isoformat(),
                    'total_records': len(export_data),
                    'data': export_data
                }, f, indent=2, default=str)
            
        elif format.lower() == 'csv':
            import csv
            filename = f"notifications_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                # Add readable timestamp column
                header = column_names + ['sent_at_readable']
                writer.writerow(header)
                
                for row in data:
                    row_list = list(row)
                    if row_list[7]:  # sent_at index
                        readable_time = datetime.fromtimestamp(row_list[7]).isoformat()
                    else:
                        readable_time = ''
                    row_list.append(readable_time)
                    writer.writerow(row_list)
        
        self.logger.info(f"Exported {len(data)} notification records to {filename}")
        return filename
        
    except Exception as e:
        self.logger.error(f"Error exporting notification data: {e}")
        return None

def create_custom_template(self, template_name, template_config):
    """Create custom notification template"""
    try:
        # Validate template config
        required_fields = ['title', 'emoji', 'color', 'priority']
        for field in required_fields:
            if field not in template_config:
                raise ValueError(f"Missing required field: {field}")
        
        # Add to templates
        self.templates[template_name] = template_config
        
        # Save to database
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO notification_templates 
            (template_name, template_data, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (
            template_name,
            json.dumps(template_config),
            int(time.time()),
            int(time.time())
        ))
        
        conn.commit()
        conn.close()
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'template_created', 
                                            f'Created custom template: {template_name}')
        
        return True
        
    except Exception as e:
        self.logger.error(f"Error creating custom template: {e}")
        return False

def load_custom_templates(self):
    """Load custom templates from database"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT template_name, template_data FROM notification_templates')
        templates = cursor.fetchall()
        
        conn.close()
        
        for template_name, template_data in templates:
            try:
                template_config = json.loads(template_data)
                self.templates[template_name] = template_config
            except json.JSONDecodeError as e:
                self.logger.error(f"Error parsing template {template_name}: {e}")
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'templates_loaded', 
                                            f'Loaded {len(templates)} custom templates')
        
    except Exception as e:
        self.logger.error(f"Error loading custom templates: {e}")

async def send_bulk_notification(self, notifications_data, batch_size=10):
    """Send multiple notifications in batches"""
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'bulk_send_start', 
                                        f'Sending {len(notifications_data)} bulk notifications')
    
    results = []
    
    # Process in batches to avoid overwhelming the queue
    for i in range(0, len(notifications_data), batch_size):
        batch = notifications_data[i:i + batch_size]
        batch_tasks = []
        
        for notif_data in batch:
            task = self.send_notification(
                notif_data.get('type', 'system_status'),
                notif_data.get('title', 'Bulk Notification'),
                notif_data.get('message', ''),
                notif_data.get('data', {}),
                notif_data.get('priority', 'medium')
            )
            batch_tasks.append(task)
        
        # Wait for batch to complete
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        results.extend(batch_results)
        
        # Small delay between batches
        if i + batch_size < len(notifications_data):
            await asyncio.sleep(1)
    
    successful = len([r for r in results if not isinstance(r, Exception)])
    failed = len(results) - successful
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'bulk_send_complete', 
                                        f'Bulk send complete - Success: {successful}, Failed: {failed}')
    
    return {'successful': successful, 'failed': failed, 'details': results}

def get_notification_preferences(self, user_id=None):
    """Get notification preferences for user or global"""
    # This could be extended to support per-user preferences
    return {
        'enabled_platforms': [platform for platform in ['telegram', 'discord', 'email', 'slack'] 
                                if self.config.get(platform, {}).get('enabled', False)],
        'notification_types': {
            platform: self.config.get(platform, {}).get('notification_types', {})
            for platform in ['telegram', 'discord', 'email', 'slack']
        },
        'priority_filter': self.config.get('priority_filter', 'low'),
        'rate_limits': self.rate_limits
    }

def update_notification_preferences(self, preferences):
    """Update notification preferences"""
    try:
        # Update configuration
        for platform, settings in preferences.items():
            if platform in self.config:
                self.config[platform].update(settings)
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'preferences_updated', 
                                            'Notification preferences updated')
        
        return True
        
    except Exception as e:
        self.logger.error(f"Error updating notification preferences: {e}")
        return False

async def pause_notifications(self, duration_minutes=0):
    """Pause notifications for specified duration (0 = indefinite)"""
    self.is_processing = False
    
    if duration_minutes > 0:
        # Resume after specified duration
        await asyncio.sleep(duration_minutes * 60)
        self.is_processing = True
        self._start_queue_processor()
    
    if self.advanced_logger:
        status = f"for {duration_minutes} minutes" if duration_minutes > 0 else "indefinitely"
        self.advanced_logger.debug_step('notifications', 'notifications_paused', 
                                        f'Notifications paused {status}')

async def resume_notifications(self):
    """Resume paused notifications"""
    if not self.is_processing:
        self.is_processing = True
        self._start_queue_processor()
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'notifications_resumed', 
                                            'Notifications resumed')

def get_queue_status(self):
    """Get detailed queue status"""
    return {
        'queue_size': self.notification_queue.qsize(),
        'is_processing': self.is_processing,
        'rate_limits': self.rate_limits,
        'delivery_stats': self.delivery_stats
    }

async def flush_queue(self):
    """Process all remaining notifications in queue immediately"""
    if self.advanced_logger:
        queue_size = self.notification_queue.qsize()
        self.advanced_logger.debug_step('notifications', 'queue_flush_start', 
                                        f'Flushing {queue_size} notifications from queue')
    
    processed = 0
    while not self.notification_queue.empty():
        try:
            notification = await asyncio.wait_for(
                self.notification_queue.get(), 
                timeout=1.0
            )
            await self._process_single_notification(notification)
            self.notification_queue.task_done()
            processed += 1
        except asyncio.TimeoutError:
            break
        except Exception as e:
            self.logger.error(f"Error flushing queue: {e}")
            break
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'queue_flush_complete', 
                                        f'Processed {processed} notifications during flush')
    
    return processed

async def shutdown(self):
    """Gracefully shutdown notification manager"""
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'shutdown_start', 
                                        'Starting notification manager shutdown')
    
    # Stop processing new notifications
    self.is_processing = False
    
    # Flush remaining notifications
    await self.flush_queue()
    
    # Close database connections (if any are persistent)
    # Clean up resources
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'shutdown_complete', 
                                        'Notification manager shutdown complete')

# Utility functions for easy integration

def create_notification_manager(config):
    """Factory function to create notification manager"""
    return NotificationManager(config)

async def send_quick_alert(alert_type, message, config=None):
    """Quick alert function for simple integrations"""
    if config is None:
        # Minimal configuration for testing
        config = {
            'notifications': {
                'telegram': {'enabled': False},
                'discord': {'enabled': False},
                'email': {'enabled': False},
                'slack': {'enabled': False},
                'webhook': {'enabled': False},
                'push': {'enabled': False}
            }
        }

manager = NotificationManager(config)
    return await manager.send_notification(alert_type, f"Quick Alert: {alert_type}", message)

def get_default_config():
"""Get default notification configuration template"""
return {
    'notifications': {
        'max_retries': 3,
        'priority_filter': 'low',
        'telegram': {
            'enabled': False,
            'bot_token': '',
            'chat_ids': [],
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': True,
                'system_status': False,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'discord': {
            'enabled': False,
            'webhook_url': '',
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': True,
                'system_status': False,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'email': {
            'enabled': False,
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'username': '',
            'password': '',
            'recipients': [],
            'notification_types': {
                'rug_alert': True,
                'pump_alert': False,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': False,
                'system_status': True,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'slack': {
            'enabled': False,
            'webhook_url': '',
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': True,
                'system_status': True,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'webhook': {
            'enabled': False,
            'urls': [],
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': True,
                'system_status': True,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'push': {
            'enabled': False,
            'service': 'pushbullet',  # or 'ntfy'
            'api_key': '',  # for pushbullet
            'topic': '',    # for ntfy
            'server': '',   # for custom ntfy server
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': False,
                'trade_notification': False,
                'system_status': False,
                'error_alert': True,
                'performance_alert': False
            }
        }
    }
}"""
Multi-Platform Notification System
File: notifications.py

Comprehensive notification manager supporting:
- Telegram (with rich formatting and buttons)
- Discord (with embeds and webhooks)
- Email (with HTML templates)
- Slack (with blocks and attachments)
- Push notifications
- Custom webhooks
"""

import asyncio
import logging
import smtplib
import json
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import sqlite3
import time
import aiohttp
from typing import Dict, List, Optional, Union
import hashlib
from dataclasses import dataclass
from enum import Enum

try:
import telegram
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
TELEGRAM_AVAILABLE = True
except ImportError:
TELEGRAM_AVAILABLE = False
print("⚠️  python-telegram-bot not installed. Telegram notifications disabled.")

class NotificationPriority(Enum):
LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"

class NotificationStatus(Enum):
PENDING = "pending"
SENT = "sent"
FAILED = "failed"
RETRYING = "retrying"

@dataclass
class NotificationItem:
"""Data class for notification queue items"""
id: str
notification_type: str
title: str
message: str
data: Dict
template: Dict
priority: NotificationPriority
platforms: List[str]
retry_count: int = 0
max_retries: int = 3
created_at: float = None

def __post_init__(self):
    if self.created_at is None:
        self.created_at = time.time()

class NotificationManager:
"""
Advanced multi-platform notification system

Features:
- 📱 Telegram with rich formatting, buttons, and inline keyboards
- 🎮 Discord with colorful embeds and webhook integration  
- 📧 Email with HTML templates and attachments
- 💬 Slack with blocks and rich formatting
- 🔔 Push notifications via various services
- 📊 Notification analytics and delivery tracking
- 🔄 Retry logic with exponential backoff
- 🎯 Smart notification routing and filtering
"""

def __init__(self, config):
    self.config = config['notifications']
    self.logger = logging.getLogger(__name__)
    self.advanced_logger = None
    
    # Initialize notification channels
    self.telegram_bot = None
    self.notification_queue = asyncio.Queue()
    self.is_processing = False
    self.delivery_stats = {
        'telegram': {'sent': 0, 'failed': 0, 'retries': 0},
        'discord': {'sent': 0, 'failed': 0, 'retries': 0},
        'email': {'sent': 0, 'failed': 0, 'retries': 0},
        'slack': {'sent': 0, 'failed': 0, 'retries': 0},
        'webhook': {'sent': 0, 'failed': 0, 'retries': 0},
        'push': {'sent': 0, 'failed': 0, 'retries': 0}
    }
    
    # Rate limiting
    self.rate_limits = {
        'telegram': {'max_per_minute': 30, 'current': 0, 'last_reset': time.time()},
        'discord': {'max_per_minute': 30, 'current': 0, 'last_reset': time.time()},
        'email': {'max_per_minute': 10, 'current': 0, 'last_reset': time.time()},
        'slack': {'max_per_minute': 20, 'current': 0, 'last_reset': time.time()}
    }
    
    # Initialize components
    self._initialize_telegram()
    self._initialize_templates()
    self._setup_database()
    self._start_queue_processor()
    
    self.logger.info("🔔 Notification Manager initialized")
    
def set_advanced_logger(self, advanced_logger):
    """Set advanced logger instance"""
    self.advanced_logger = advanced_logger
    
def _initialize_telegram(self):
    """Initialize Telegram bot if enabled and available"""
    if not TELEGRAM_AVAILABLE:
        self.logger.warning("📱 Telegram bot library not available")
        return
        
    telegram_config = self.config.get('telegram', {})
    if telegram_config.get('enabled') and telegram_config.get('bot_token'):
        try:
            self.telegram_bot = Bot(token=telegram_config['bot_token'])
            self.logger.info("📱 Telegram bot initialized successfully")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('notifications', 'telegram_init_success', 
                                                'Telegram bot initialized')
        except Exception as e:
            self.logger.error(f"📱 Failed to initialize Telegram bot: {e}")
            if self.advanced_logger:
                self.advanced_logger.debug_step('notifications', 'telegram_init_failed', 
                                                f'Telegram init failed: {e}')
            
def _initialize_templates(self):
    """Initialize notification templates"""
    self.templates = {
        'rug_alert': {
            'title': '🚨 RUG PULL ALERT',
            'color': 0xFF0000,  # Red
            'emoji': '🚨',
            'priority': NotificationPriority.CRITICAL
        },
        'pump_alert': {
            'title': '🚀 PUMP DETECTED', 
            'color': 0x00FF00,  # Green
            'emoji': '🚀',
            'priority': NotificationPriority.HIGH
        },
        'fake_volume_alert': {
            'title': '📊 FAKE VOLUME DETECTED',
            'color': 0xFF8C00,  # Orange
            'emoji': '📊',
            'priority': NotificationPriority.HIGH
        },
        'bundle_alert': {
            'title': '📦 BUNDLE LAUNCH DETECTED',
            'color': 0xFF4500,  # Red-Orange
            'emoji': '📦',
            'priority': NotificationPriority.HIGH
        },
        'rugcheck_failed': {
            'title': '⚠️ RUGCHECK VERIFICATION FAILED',
            'color': 0xFFFF00,  # Yellow
            'emoji': '⚠️',
            'priority': NotificationPriority.MEDIUM
        },
        'trade_notification': {
            'title': '💰 TRADE EXECUTED',
            'color': 0x00BFFF,  # Deep Sky Blue
            'emoji': '💰',
            'priority': NotificationPriority.MEDIUM
        },
        'system_status': {
            'title': '🤖 SYSTEM UPDATE',
            'color': 0x808080,  # Gray
            'emoji': '🤖',
            'priority': NotificationPriority.LOW
        },
        'error_alert': {
            'title': '💥 SYSTEM ERROR',
            'color': 0xDC143C,  # Crimson
            'emoji': '💥',
            'priority': NotificationPriority.CRITICAL
        },
        'performance_alert': {
            'title': '⚡ PERFORMANCE ALERT',
            'color': 0xFFA500,  # Orange
            'emoji': '⚡',
            'priority': NotificationPriority.MEDIUM
        }
    }
    
def _setup_database(self):
    """Setup notification tracking database"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id TEXT UNIQUE,
                notification_type TEXT,
                platform TEXT,
                recipient TEXT,
                title TEXT,
                message TEXT,
                status TEXT,
                sent_at INTEGER,
                delivery_time REAL,
                retry_count INTEGER DEFAULT 0,
                error_message TEXT,
                priority TEXT,
                data_hash TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                platform TEXT,
                notification_type TEXT,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                avg_delivery_time REAL DEFAULT 0,
                retry_count INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_name TEXT UNIQUE,
                template_data TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notification_log_date ON notification_log(sent_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notification_log_platform ON notification_log(platform)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notification_log_type ON notification_log(notification_type)')
        
        conn.commit()
        conn.close()
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'database_setup', 
                                            'Notification database initialized')
            
    except Exception as e:
        self.logger.error(f"Error setting up notification database: {e}")

def _start_queue_processor(self):
    """Start the notification queue processor"""
    if not self.is_processing:
        self.is_processing = True
        asyncio.create_task(self._process_notification_queue())
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'queue_processor_started', 
                                            'Notification queue processor started')

async def _process_notification_queue(self):
    """Process notifications from the queue with rate limiting and retries"""
    while self.is_processing:
        try:
            # Wait for notification with timeout
            try:
                notification = await asyncio.wait_for(
                    self.notification_queue.get(), 
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            
            # Check rate limits before processing
            await self._enforce_rate_limits(notification.platforms)
            
            # Process the notification
            await self._process_single_notification(notification)
            
            # Mark task as done
            self.notification_queue.task_done()
            
        except Exception as e:
            self.logger.error(f"Error in notification queue processor: {e}")
            if self.advanced_logger:
                self.advanced_logger.debug_step('notifications', 'queue_processor_error', 
                                                f'Queue processor error: {e}')
            await asyncio.sleep(1)

async def _enforce_rate_limits(self, platforms):
    """Enforce rate limits for platforms"""
    current_time = time.time()
    
    for platform in platforms:
        if platform not in self.rate_limits:
            continue
            
        rate_limit = self.rate_limits[platform]
        
        # Reset counter if a minute has passed
        if current_time - rate_limit['last_reset'] >= 60:
            rate_limit['current'] = 0
            rate_limit['last_reset'] = current_time
        
        # Wait if rate limit exceeded
        if rate_limit['current'] >= rate_limit['max_per_minute']:
            wait_time = 60 - (current_time - rate_limit['last_reset'])
            if wait_time > 0:
                if self.advanced_logger:
                    self.advanced_logger.debug_step('notifications', 'rate_limit_wait', 
                                                    f'Rate limit hit for {platform}, waiting {wait_time:.1f}s')
                await asyncio.sleep(wait_time)
                
                # Reset after waiting
                rate_limit['current'] = 0
                rate_limit['last_reset'] = time.time()

async def _process_single_notification(self, notification: NotificationItem):
    """Process a single notification with retry logic"""
    notification_id = notification.id
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'processing_notification', 
                                        f'Processing notification {notification_id}: {notification.title}')
    
    # Send to enabled platforms
    tasks = []
    
    for platform in notification.platforms:
        if platform == 'telegram' and self._should_notify('telegram', notification.notification_type):
            tasks.append(self._send_telegram_notification_safe(notification))
        elif platform == 'discord' and self._should_notify('discord', notification.notification_type):
            tasks.append(self._send_discord_notification_safe(notification))
        elif platform == 'email' and self._should_notify('email', notification.notification_type):
            tasks.append(self._send_email_notification_safe(notification))
        elif platform == 'slack' and self._should_notify('slack', notification.notification_type):
            tasks.append(self._send_slack_notification_safe(notification))
        elif platform == 'webhook':
            tasks.append(self._send_webhook_notification_safe(notification))
        elif platform == 'push':
            tasks.append(self._send_push_notification_safe(notification))
    
    # Execute all notifications concurrently
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check results and handle retries
        failed_platforms = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_platforms.append(notification.platforms[i])
                if self.advanced_logger:
                    self.advanced_logger.debug_step('notifications', 'platform_failed', 
                                                    f'Platform {notification.platforms[i]} failed: {result}')
        
        # Retry failed platforms if under retry limit
        if failed_platforms and notification.retry_count < notification.max_retries:
            notification.retry_count += 1
            notification.platforms = failed_platforms
            
            # Exponential backoff
            retry_delay = min(60, 2 ** notification.retry_count)
            await asyncio.sleep(retry_delay)
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('notifications', 'retrying_notification', 
                                                f'Retrying notification {notification_id}, attempt {notification.retry_count}')
            
            # Re-add to queue for retry
            await self.notification_queue.put(notification)

async def send_notification(self, notification_type, title, message, data=None, priority='medium'):
    """
    Main notification sending function
    
    Routes notifications to all enabled platforms based on configuration
    """
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'send_notification_start', 
                                        f'🔔 Sending {notification_type} notification: {title}')
    
    # Get template configuration
    template = self.templates.get(notification_type, self.templates['system_status'])
    
    # Generate unique notification ID
    notification_id = self._generate_notification_id(notification_type, title, message)
    
    # Determine target platforms
    target_platforms = self._get_target_platforms(notification_type)
    
    if not target_platforms:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'no_platforms_enabled', 
                                            f'No platforms enabled for {notification_type}')
        return {'success': 0, 'failed': 0, 'notification_id': notification_id}
    
    # Create notification item
    notification_item = NotificationItem(
        id=notification_id,
        notification_type=notification_type,
        title=title,
        message=message,
        data=data or {},
        template=template,
        priority=NotificationPriority(priority) if isinstance(priority, str) else priority,
        platforms=target_platforms,
        max_retries=self.config.get('max_retries', 3)
    )
    
    # Add to queue
    await self.notification_queue.put(notification_item)
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'notification_queued', 
                                        f'Notification {notification_id} queued for {len(target_platforms)} platforms')
    
    return {
        'success': 0,  # Will be updated by queue processor
        'failed': 0,
        'notification_id': notification_id,
        'queued_platforms': target_platforms
    }

def _generate_notification_id(self, notification_type, title, message):
    """Generate unique notification ID"""
    content = f"{notification_type}:{title}:{message}:{time.time()}"
    return hashlib.md5(content.encode()).hexdigest()[:12]

def _get_target_platforms(self, notification_type):
    """Get list of platforms that should receive this notification type"""
    target_platforms = []
    
    for platform in ['telegram', 'discord', 'email', 'slack', 'webhook', 'push']:
        if self._should_notify(platform, notification_type):
            target_platforms.append(platform)
    
    return target_platforms

def _should_notify(self, platform, notification_type):
    """Check if notification should be sent to specific platform"""
    platform_config = self.config.get(platform, {})
    
    if not platform_config.get('enabled', False):
        return False
        
    notification_types = platform_config.get('notification_types', {})
    return notification_types.get(notification_type, False)

async def _send_telegram_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for Telegram notifications with error handling"""
    try:
        await self._send_telegram_notification(notification)
        self.rate_limits['telegram']['current'] += 1
        self.delivery_stats['telegram']['sent'] += 1
    except Exception as e:
        self.delivery_stats['telegram']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['telegram']['retries'] += 1
        raise e

async def _send_telegram_notification(self, notification: NotificationItem):
    """
    Send rich Telegram notification with formatting and buttons
    """
    if not self.telegram_bot:
        raise Exception("Telegram bot not initialized")
        
    start_time = time.time()
    
    try:
        template = notification.template
        title = notification.title
        message = notification.message
        data = notification.data
        
        # Format message with Telegram markdown
        formatted_message = f"*{template['emoji']} {title}*\n\n{message}"
        
        # Add data fields if present
        if data:
            formatted_message += "\n\n📊 *Details:*"
            for key, value in data.items():
                if key in ['timestamp', 'analysis_timestamp']:
                    continue  # Skip internal timestamps
                    
                if isinstance(value, (int, float)):
                    if 'usd' in key.lower() or 'price' in key.lower():
                        formatted_message += f"\n• *{self._format_field_name(key)}:* ${value:,.2f}"
                    elif 'confidence' in key.lower() or 'score' in key.lower():
                        formatted_message += f"\n• *{self._format_field_name(key)}:* {value:.1%}"
                    else:
                        formatted_message += f"\n• *{self._format_field_name(key)}:* {value:,}"
                else:
                    formatted_message += f"\n• *{self._format_field_name(key)}:* {value}"
        
        # Add timestamp
        formatted_message += f"\n\n🕐 {datetime.now().strftime('%H:%M:%S UTC')}"
        
        # Create inline keyboard for interactive buttons
        keyboard = self._create_telegram_keyboard(notification)
        
        # Send to all configured chat IDs
        telegram_config = self.config['telegram']
        for chat_id in telegram_config['chat_ids']:
            try:
                await self.telegram_bot.send_message(
                    chat_id=chat_id,
                    text=formatted_message,
                    parse_mode='Markdown',
                    disable_web_page_preview=True,
                    reply_markup=keyboard
                )
                
                delivery_time = time.time() - start_time
                
                # Log successful delivery
                self._log_notification_delivery(
                    notification.id, notification.notification_type, 'telegram', chat_id,
                    title, message, 'sent', delivery_time, notification.retry_count
                )
                
                if self.advanced_logger:
                    self.advanced_logger.log_notification_sent('notifications', 
                                                                notification.notification_type, 
                                                                'telegram', True,
                                                                f'Delivered in {delivery_time:.3f}s')
                
            except Exception as e:
                self.logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
                self._log_notification_delivery(
                    notification.id, notification.notification_type, 'telegram', chat_id,
                    title, message, 'failed', 0, notification.retry_count, str(e)
                )
                raise e
                
    except Exception as e:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'telegram_send_error', 
                                            f'❌ Telegram notification failed: {e}')
        raise

def _create_telegram_keyboard(self, notification: NotificationItem):
    """Create interactive keyboard for Telegram notifications"""
    if not TELEGRAM_AVAILABLE:
        return None
        
    notification_type = notification.notification_type
    data = notification.data
    
    keyboard = []
    
    # Add relevant action buttons based on notification type
    if notification_type in ['rug_alert', 'fake_volume_alert', 'bundle_alert']:
        keyboard.append([
            InlineKeyboardButton("🚫 Add to Blacklist", callback_data=f"blacklist_{data.get('token_address', '')}")
        ])
        
    if notification_type == 'pump_alert':
        keyboard.append([
            InlineKeyboardButton("💰 Check Trading", callback_data=f"trade_check_{data.get('token_address', '')}")
        ])
        
    # Always add info button
    if data.get('token_address'):
        keyboard.append([
            InlineKeyboardButton("📊 View on DexScreener", 
                                url=f"https://dexscreener.com/solana/{data['token_address']}")
        ])
        
    # Add notification management buttons
    keyboard.append([
        InlineKeyboardButton("🔕 Mute Type", callback_data=f"mute_{notification_type}"),
        InlineKeyboardButton("📊 Stats", callback_data="show_stats")
    ])
        
    if keyboard:
        return InlineKeyboardMarkup(keyboard)
    return None

async def _send_discord_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for Discord notifications"""
    try:
        await self._send_discord_notification(notification)
        self.rate_limits['discord']['current'] += 1
        self.delivery_stats['discord']['sent'] += 1
    except Exception as e:
        self.delivery_stats['discord']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['discord']['retries'] += 1
        raise e

async def _send_discord_notification(self, notification: NotificationItem):
    """
    Send rich Discord webhook notification with embeds
    """
    discord_config = self.config.get('discord', {})
    webhook_url = discord_config.get('webhook_url')
    
    if not webhook_url:
        raise Exception("Discord webhook URL not configured")
        
    start_time = time.time()
    
    try:
        template = notification.template
        title = notification.title
        message = notification.message
        data = notification.data
        
        # Create rich embed
        embed = {
            "title": f"{template['emoji']} {title}",
            "description": message,
            "color": template['color'],
            "timestamp": datetime.now().isoformat(),
            "footer": {
                "text": "DexScreener Solana Bot",
                "icon_url": "https://dexscreener.com/favicon.ico"
            },
            "fields": []
        }
        
        # Add priority indicator
        priority_emojis = {
            NotificationPriority.LOW: "🟢",
            NotificationPriority.MEDIUM: "🟡", 
            NotificationPriority.HIGH: "🟠",
            NotificationPriority.CRITICAL: "🔴"
        }
        
        embed["fields"].append({
            "name": "Priority",
            "value": f"{priority_emojis.get(notification.priority, '⚪')} {notification.priority.value.title()}",
            "inline": True
        })
        
        # Add data fields
        if data:
            for key, value in data.items():
                if key in ['timestamp', 'analysis_timestamp']:
                    continue
                    
                field_value = str(value)
                if isinstance(value, (int, float)):
                    if 'usd' in key.lower() or 'price' in key.lower():
                        field_value = f"${value:,.2f}"
                    elif 'confidence' in key.lower() or 'score' in key.lower():
                        field_value = f"{value:.1%}"
                    else:
                        field_value = f"{value:,}"
                
                embed["fields"].append({
                    "name": self._format_field_name(key),
                    "value": field_value,
                    "inline": True
                })
        
        # Add DexScreener link if token address available
        if data.get('token_address'):
            embed["url"] = f"https://dexscreener.com/solana/{data['token_address']}"
        
        # Add retry info if this is a retry
        if notification.retry_count > 0:
            embed["fields"].append({
                "name": "Retry Info",
                "value": f"Attempt {notification.retry_count + 1}/{notification.max_retries + 1}",
                "inline": True
            })
        
        payload = {"embeds": [embed]}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10) as response:
                response.raise_for_status()
        
        delivery_time = time.time() - start_time
        
        # Log successful delivery
        self._log_notification_delivery(
            notification.id, notification.notification_type, 'discord', 'webhook',
            title, message, 'sent', delivery_time, notification.retry_count
        )
        
        if self.advanced_logger:
            self.advanced_logger.log_notification_sent('notifications', 
                                                        notification.notification_type, 
                                                        'discord', True,
                                                        f'Delivered in {delivery_time:.3f}s')
        
    except Exception as e:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'discord_send_error', 
                                            f'❌ Discord notification failed: {e}')
        raise

async def _send_email_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for Email notifications"""
    try:
        await self._send_email_notification(notification)
        self.rate_limits['email']['current'] += 1
        self.delivery_stats['email']['sent'] += 1
    except Exception as e:
        self.delivery_stats['email']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['email']['retries'] += 1
        raise e

async def _send_email_notification(self, notification: NotificationItem):
    """
    Send HTML email notification with rich formatting
    """
    email_config = self.config.get('email', {})
    
    if not all([email_config.get('username'), email_config.get('password'), 
                email_config.get('recipients')]):
        raise Exception("Email configuration incomplete")
        
    start_time = time.time()
    
    try:
        template = notification.template
        title = notification.title
        message = notification.message
        data = notification.data
        
        # Create HTML email
        html_content = self._create_html_email(notification)
        
        msg = MIMEMultipart('alternative')
        msg['From'] = email_config['username']
        msg['Subject'] = f"[DexScreener Bot] {template['emoji']} {title}"
        
        # Add priority headers
        if notification.priority == NotificationPriority.CRITICAL:
            msg['X-Priority'] = '1'
            msg['X-MSMail-Priority'] = 'High'
            msg['Importance'] = 'High'
        
        # Add HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        # Send to all recipients
        server = smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port'])
        server.starttls()
        server.login(email_config['username'], email_config['password'])
        
        for recipient in email_config['recipients']:
            msg['To'] = recipient
            server.send_message(msg)
            
            delivery_time = time.time() - start_time
            
            self._log_notification_delivery(
                notification.id, notification.notification_type, 'email', recipient,
                title, message, 'sent', delivery_time, notification.retry_count
            )
        
        server.quit()
        
        if self.advanced_logger:
            self.advanced_logger.log_notification_sent('notifications', 
                                                        notification.notification_type, 
                                                        'email', True,
                                                        f'Sent to {len(email_config["recipients"])} recipients')
        
    except Exception as e:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'email_send_error', 
                                            f'❌ Email notification failed: {e}')
        raise

async def _send_slack_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for Slack notifications"""
    try:
        await self._send_slack_notification(notification)
        self.rate_limits['slack']['current'] += 1
        self.delivery_stats['slack']['sent'] += 1
    except Exception as e:
        self.delivery_stats['slack']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['slack']['retries'] += 1
        raise e notification.retry_count > 0:
            self.delivery_stats['slack']['retries'] += 1
        raise e

async def _send_slack_notification(self, notification: NotificationItem):
    """
    Send Slack notification with blocks and rich formatting
    """
    slack_config = self.config.get('slack', {})
    webhook_url = slack_config.get('webhook_url')
    
    if not webhook_url:
        raise Exception("Slack webhook URL not configured")
        
    start_time = time.time()
    
    try:
        template = notification.template
        title = notification.title
        message = notification.message
        data = notification.data
        
        # Create Slack blocks
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{template['emoji']} {title}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            }
        ]
        
        # Add priority indicator
        priority_colors = {
            NotificationPriority.LOW: "good",
            NotificationPriority.MEDIUM: "warning",
            NotificationPriority.HIGH: "danger",
            NotificationPriority.CRITICAL: "danger"
        }
        
        # Add data fields
        if data:
            fields = []
            for key, value in data.items():
                if key in ['timestamp', 'analysis_timestamp']:
                    continue
                    
                field_value = str(value)
                if isinstance(value, (int, float)):
                    if 'usd' in key.lower():
                        field_value = f"${value:,.2f}"
                    elif 'confidence' in key.lower() or 'score' in key.lower():
                        field_value = f"{value:.1%}"
                        
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*{self._format_field_name(key)}:*\n{field_value}"
                })
            
            if fields:
                blocks.append({
                    "type": "section",
                    "fields": fields[:10]  # Slack limits to 10 fields
                })
        
        # Add action buttons
        if data.get('token_address'):
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "📊 View on DexScreener"
                        },
                        "url": f"https://dexscreener.com/solana/{data['token_address']}"
                    }
                ]
            })
        
        # Add timestamp and retry info
        context_elements = [
            {
                "type": "mrkdwn",
                "text": f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            }
        ]
        
        if notification.retry_count > 0:
            context_elements.append({
                "type": "mrkdwn", 
                "text": f"🔄 Retry {notification.retry_count}/{notification.max_retries}"
            })
        
        blocks.append({
            "type": "context",
            "elements": context_elements
        })
        
        payload = {
            "blocks": blocks,
            "attachments": [
                {
                    "color": priority_colors.get(notification.priority, "good"),
                    "fallback": f"{title}: {message}"
                }
            ]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10) as response:
                response.raise_for_status()
        
        delivery_time = time.time() - start_time
        
        self._log_notification_delivery(
            notification.id, notification.notification_type, 'slack', 'webhook',
            title, message, 'sent', delivery_time, notification.retry_count
        )
        
        if self.advanced_logger:
            self.advanced_logger.log_notification_sent('notifications', 
                                                        notification.notification_type, 
                                                        'slack', True,
                                                        f'Delivered in {delivery_time:.3f}s')
        
    except Exception as e:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'slack_send_error', 
                                            f'❌ Slack notification failed: {e}')
        raise

async def _send_webhook_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for custom webhook notifications"""
    try:
        await self._send_webhook_notification(notification)
        self.delivery_stats['webhook']['sent'] += 1
    except Exception as e:
        self.delivery_stats['webhook']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['webhook']['retries'] += 1
        raise e

async def _send_webhook_notification(self, notification: NotificationItem):
    """Send custom webhook notification"""
    webhook_config = self.config.get('webhook', {})
    webhook_urls = webhook_config.get('urls', [])
    
    if not webhook_urls:
        raise Exception("No webhook URLs configured")
    
    start_time = time.time()
    
    payload = {
        "notification_id": notification.id,
        "type": notification.notification_type,
        "title": notification.title,
        "message": notification.message,
        "data": notification.data,
        "priority": notification.priority.value,
        "retry_count": notification.retry_count,
        "timestamp": datetime.now().isoformat()
    }
    
    for webhook_url in webhook_urls:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url, 
                    json=payload, 
                    timeout=10,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    response.raise_for_status()
            
            delivery_time = time.time() - start_time
            
            self._log_notification_delivery(
                notification.id, notification.notification_type, 'webhook', webhook_url,
                notification.title, notification.message, 'sent', delivery_time, notification.retry_count
            )
            
        except Exception as e:
            self.logger.error(f"Failed to send webhook notification to {webhook_url}: {e}")
            self._log_notification_delivery(
                notification.id, notification.notification_type, 'webhook', webhook_url,
                notification.title, notification.message, 'failed', 0, notification.retry_count, str(e)
            )
            raise e

async def _send_push_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for push notifications"""
    try:
        await self._send_push_notification(notification)
        self.delivery_stats['push']['sent'] += 1
    except Exception as e:
        self.delivery_stats['push']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['push']['retries'] += 1
        raise e

async def _send_push_notification(self, notification: NotificationItem):
    """Send push notification via Pushbullet or similar service"""
    push_config = self.config.get('push', {})
    service = push_config.get('service', 'pushbullet')
    
    if service == 'pushbullet':
        await self._send_pushbullet_notification(notification, push_config)
    elif service == 'ntfy':
        await self._send_ntfy_notification(notification, push_config)
    else:
        raise Exception(f"Unsupported push service: {service}")

async def _send_pushbullet_notification(self, notification: NotificationItem, config):
    """Send notification via Pushbullet"""
    api_key = config.get('api_key')
    if not api_key:
        raise Exception("Pushbullet API key not configured")
    
    start_time = time.time()
    
    payload = {
        "type": "note",
        "title": f"{notification.template['emoji']} {notification.title}",
        "body": notification.message
    }
    
    headers = {
        "Access-Token": api_key,
        "Content-Type": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.pushbullet.com/v2/pushes",
            json=payload,
            headers=headers,
            timeout=10
        ) as response:
            response.raise_for_status()
    
    delivery_time = time.time() - start_time
    
    self._log_notification_delivery(
        notification.id, notification.notification_type, 'push', 'pushbullet',
        notification.title, notification.message, 'sent', delivery_time, notification.retry_count
    )

async def _send_ntfy_notification(self, notification: NotificationItem, config):
    """Send notification via ntfy.sh"""
    topic = config.get('topic')
    if not topic:
        raise Exception("ntfy topic not configured")
    
    start_time = time.time()
    
    headers = {
        "Title": f"{notification.template['emoji']} {notification.title}",
        "Priority": self._get_ntfy_priority(notification.priority),
        "Tags": self._get_ntfy_tags(notification.notification_type)
    }
    
    url = f"https://ntfy.sh/{topic}"
    if config.get('server'):
        url = f"{config['server']}/{topic}"
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            data=notification.message,
            headers=headers,
            timeout=10
        ) as response:
            response.raise_for_status()
    
    delivery_time = time.time() - start_time
    
    self._log_notification_delivery(
        notification.id, notification.notification_type, 'push', 'ntfy',
        notification.title, notification.message, 'sent', delivery_time, notification.retry_count
    )

def _get_ntfy_priority(self, priority: NotificationPriority) -> str:
    """Convert notification priority to ntfy priority"""
    mapping = {
        NotificationPriority.LOW: "2",
        NotificationPriority.MEDIUM: "3",
        NotificationPriority.HIGH: "4",
        NotificationPriority.CRITICAL: "5"
    }
    return mapping.get(priority, "3")

def _get_ntfy_tags(self, notification_type: str) -> str:
    """Get appropriate tags for ntfy notification"""
    tag_mapping = {
        'rug_alert': 'warning,skull',
        'pump_alert': 'rocket,money',
        'fake_volume_alert': 'chart,warning',
        'bundle_alert': 'package,warning',
        'rugcheck_failed': 'shield,warning',
        'trade_notification': 'money,check',
        'system_status': 'robot,info',
        'error_alert': 'boom,warning',
        'performance_alert': 'zap,warning'
    }
    return tag_mapping.get(notification_type, 'info')

def _create_html_email(self, notification: NotificationItem):
    """Create rich HTML email template"""
    template = notification.template
    title = notification.title
    message = notification.message
    data = notification.data
    
    # Color based on priority
    priority_colors = {
        NotificationPriority.LOW: "#e6f3ff",
        NotificationPriority.MEDIUM: "#fff2e6", 
        NotificationPriority.HIGH: "#ffe6e6",
        NotificationPriority.CRITICAL: "#ff4444"
    }
    
    bg_color = priority_colors.get(notification.priority, "#f8f9fa")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>DexScreener Bot Alert</title>
        <style>
            .priority-indicator {{
                display: inline-block;
                padding: 4px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                background-color: {template.get('color', '#666')};
            }}
            .retry-info {{
                background-color: #fff3cd;
                border: 1px solid #ffeaa7;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
            }}
        </style>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: {bg_color}; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0; font-size: 24px;">{template['emoji']} {title}</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">DexScreener Solana Bot</p>
                <span class="priority-indicator">{notification.priority.value.upper()}</span>
            </div>
            
            <div style="padding: 20px;">
                <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px;">{message}</p>
                
                {f'<div class="retry-info"><strong>⚠️ Retry Attempt:</strong> {notification.retry_count}/{notification.max_retries}</div>' if notification.retry_count > 0 else ''}
                
                {"<h3>Details:</h3>" if data else ""}
                <table style="width: 100%; border-collapse: collapse;">
    """
    
    # Add data rows
    if data:
        for key, value in data.items():
            if key in ['timestamp', 'analysis_timestamp']:
                continue
                
            formatted_value = str(value)
            if isinstance(value, (int, float)):
                if 'usd' in key.lower():
                    formatted_value = f"${value:,.2f}"
                elif 'confidence' in key.lower() or 'score' in key.lower():
                    formatted_value = f"{value:.1%}"
                    
            html += f"""
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">{self._format_field_name(key)}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">{formatted_value}</td>
                </tr>
            """
    
    html += f"""
                </table>
                
                <div style="margin-top: 30px; padding: 15px; background-color: #f8f9fa; border-radius: 5px; text-align: center;">
                    <p style="margin: 0; color: #666; font-size: 14px;">
                        🕐 Sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}<br>
                        Generated by DexScreener Solana Bot<br>
                        Notification ID: {notification.id}
                    </p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

def _format_field_name(self, field_name):
    """Format field names for display"""
    return field_name.replace('_', ' ').title()

def _log_notification_delivery(self, notification_id, notification_type, platform, recipient, 
                                title, message, status, delivery_time, retry_count=0, error_message=None):
    """Log notification delivery to database"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        # Create data hash for deduplication
        data_content = f"{notification_type}:{title}:{message}"
        data_hash = hashlib.md5(data_content.encode()).hexdigest()
        
        cursor.execute('''
            INSERT OR REPLACE INTO notification_log 
            (notification_id, notification_type, platform, recipient, title, message, status, 
                sent_at, delivery_time, retry_count, error_message, priority, data_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            notification_id, notification_type, platform, recipient, title, message[:500], status,
            int(time.time()), delivery_time, retry_count, error_message, 'medium', data_hash
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        self.logger.error(f"Error logging notification delivery: {e}")

async def send_alert_notification(self, alert_type, symbol, confidence, indicators, additional_data=None):
    """
    Send alert notification with standardized formatting
    
    Wrapper function for common alert types
    """
    template = self.templates.get(f"{alert_type}_alert", self.templates['system_status'])
    
    # Create message based on alert type
    if alert_type == 'rug':
        message = f"⚠️ Potential rug pull detected for *{symbol}* with {confidence:.1%} confidence"
    elif alert_type == 'pump':
        message = f"📈 Price pump detected for *{symbol}* with {confidence:.1%} confidence"
    elif alert_type == 'fake_volume':
        message = f"🎭 Fake volume detected for *{symbol}* with score {confidence:.3f}"
    elif alert_type == 'bundle':
        message = f"📦 Bundle launch detected for *{symbol}* with {confidence:.1%} confidence"
    elif alert_type == 'rugcheck_failed':
        message = f"🔒 RugCheck verification failed for *{symbol}*"
    else:
        message = f"Alert detected for *{symbol}*"
    
    # Add indicators
    if indicators:
        message += f"\n\n🔍 *Key Indicators:*"
        for indicator in indicators[:3]:  # Show top 3 indicators
            message += f"\n• {indicator}"
    
    # Combine with additional data
    notification_data = {'symbol': symbol, 'confidence': confidence}
    if additional_data:
        notification_data.update(additional_data)
        
    await self.send_notification(
        f'{alert_type}_alert',
        template['title'].format(symbol=symbol),
        message,
        notification_data,
        template['priority'].value
    )

async def send_system_notification(self, title, message, data=None, priority='low'):
    """Send system status notification"""
    await self.send_notification('system_status', title, message, data, priority)

async def send_trade_notification(self, action, symbol, amount, data=None):
    """Send trading notification"""
    title = f"💰 {action.upper()} ORDER: {symbol}"
    message = f"Trade executed: {action} {amount} SOL of {symbol}"
    
    await self.send_notification('trade_notification', title, message, data, 'medium')

async def send_error_notification(self, error_type, error_message, data=None):
    """Send error notification"""
    title = f"💥 SYSTEM ERROR: {error_type}"
    message = f"Error detected: {error_message}"
    
    await self.send_notification('error_alert', title, message, data, 'critical')

async def send_performance_alert(self, metric, value, threshold, data=None):
    """Send performance alert"""
    title = f"⚡ PERFORMANCE ALERT: {metric}"
    message = f"Metric {metric} is {value}, exceeding threshold of {threshold}"
    
    await self.send_notification('performance_alert', title, message, data, 'medium')

def get_stats(self):
    """Get comprehensive notification statistics"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        # Get today's stats
        today = datetime.now().strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT platform, notification_type, COUNT(*) as count, 
                    AVG(delivery_time) as avg_time, status
            FROM notification_log 
            WHERE date(sent_at, 'unixepoch') = ?
            GROUP BY platform, notification_type, status
        ''', (today,))
        
        daily_stats = cursor.fetchall()
        
        # Get overall stats
        cursor.execute('''
            SELECT platform, COUNT(*) as total, 
                    SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) as sent,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    AVG(delivery_time) as avg_delivery_time
            FROM notification_log 
            GROUP BY platform
        ''')
        
        overall_stats = cursor.fetchall()
        
        # Get recent failed notifications
        cursor.execute('''
            SELECT notification_type, platform, error_message, sent_at
            FROM notification_log 
            WHERE status = 'failed' AND sent_at > ?
            ORDER BY sent_at DESC
            LIMIT 10
        ''', (int(time.time()) - 3600,))  # Last hour
        
        recent_failures = cursor.fetchall()
        
        # Get retry statistics
        cursor.execute('''
            SELECT platform, AVG(retry_count) as avg_retries, 
                    MAX(retry_count) as max_retries
            FROM notification_log 
            WHERE retry_count > 0
            GROUP BY platform
        ''')
        
        retry_stats = cursor.fetchall()
        
        conn.close()
        
        return {
            'daily_stats': [dict(zip(['platform', 'type', 'count', 'avg_time', 'status'], row)) 
                            for row in daily_stats],
            'overall_stats': [dict(zip(['platform', 'total', 'sent', 'failed', 'avg_delivery_time'], row)) 
                                for row in overall_stats],
            'recent_failures': [dict(zip(['type', 'platform', 'error', 'timestamp'], row)) 
                                for row in recent_failures],
            'retry_stats': [dict(zip(['platform', 'avg_retries', 'max_retries'], row)) 
                            for row in retry_stats],
            'current_stats': self.delivery_stats,
            'queue_size': self.notification_queue.qsize(),
            'is_processing': self.is_processing
        }
        
    except Exception as e:
        self.logger.error(f"Error getting notification stats: {e}")
        return {
            'error': str(e),
            'current_stats': self.delivery_stats,
            'queue_size': self.notification_queue.qsize(),
            'is_processing': self.is_processing
        }

def get_delivery_health(self):
    """Get delivery health metrics"""
    stats = self.get_stats()
    health_score = 100
    issues = []
    
    # Check overall delivery success rate
    for platform_stats in stats.get('overall_stats', []):
        platform = platform_stats['platform']
        total = platform_stats['total']
        sent = platform_stats['sent']
        
        if total > 0:
            success_rate = sent / total
            if success_rate < 0.9:  # Less than 90% success
                health_score -= 15
                issues.append(f"{platform} has low success rate: {success_rate:.1%}")
            elif success_rate < 0.95:  # Less than 95% success
                health_score -= 5
                issues.append(f"{platform} has moderate success rate: {success_rate:.1%}")
    
    # Check recent failures
    recent_failures = len(stats.get('recent_failures', []))
    if recent_failures > 10:
        health_score -= 20
        issues.append(f"High number of recent failures: {recent_failures}")
    elif recent_failures > 5:
        health_score -= 10
        issues.append(f"Moderate number of recent failures: {recent_failures}")
    
    # Check queue size
    queue_size = stats.get('queue_size', 0)
    if queue_size > 100:
        health_score -= 15
        issues.append(f"Large queue backlog: {queue_size} notifications")
    elif queue_size > 50:
        health_score -= 5
        issues.append(f"Moderate queue backlog: {queue_size} notifications")
    
    # Determine health status
    if health_score >= 90:
        status = "EXCELLENT"
    elif health_score >= 75:
        status = "GOOD"
    elif health_score >= 60:
        status = "FAIR"
    elif health_score >= 40:
        status = "POOR"
    else:
        status = "CRITICAL"
    
    return {
        'health_score': max(0, health_score),
        'status': status,
        'issues': issues,
        'recommendations': self._get_health_recommendations(issues)
    }

def _get_health_recommendations(self, issues):
    """Get recommendations based on health issues"""
    recommendations = []
    
    for issue in issues:
        if 'success rate' in issue:
            recommendations.append("Check platform configurations and API credentials")
        elif 'failures' in issue:
            recommendations.append("Review error logs and increase retry limits")
        elif 'queue backlog' in issue:
            recommendations.append("Consider increasing concurrent workers or optimizing delivery")
    
    if not recommendations:
        recommendations.append("System is operating normally")
    
    return recommendations

async def test_connectivity(self):
    """Test connectivity to all configured notification platforms"""
    test_results = {}
    
    # Test Telegram
    if self.config.get('telegram', {}).get('enabled'):
        try:
            if self.telegram_bot:
                bot_info = await self.telegram_bot.get_me()
                test_results['telegram'] = {'status': 'success', 'bot_name': bot_info.first_name}
            else:
                test_results['telegram'] = {'status': 'failed', 'error': 'Bot not initialized'}
        except Exception as e:
            test_results['telegram'] = {'status': 'failed', 'error': str(e)}
    
    # Test Discord
    if self.config.get('discord', {}).get('enabled'):
        try:
            webhook_url = self.config['discord']['webhook_url']
            async with aiohttp.ClientSession() as session:
                test_payload = {"content": "🧪 Connectivity test"}
                async with session.post(webhook_url, json=test_payload, timeout=5) as response:
                    if response.status == 204:
                        test_results['discord'] = {'status': 'success'}
                    else:
                        test_results['discord'] = {'status': 'failed', 'error': f'HTTP {response.status}'}
        except Exception as e:
            test_results['discord'] = {'status': 'failed', 'error': str(e)}
    
    # Test Email
    if self.config.get('email', {}).get('enabled'):
        try:
            email_config = self.config['email']
            server = smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port'])
            server.starttls()
            server.login(email_config['username'], email_config['password'])
            server.quit()
            test_results['email'] = {'status': 'success'}
        except Exception as e:
            test_results['email'] = {'status': 'failed', 'error': str(e)}
    
    # Test Slack
    if self.config.get('slack', {}).get('enabled'):
        try:
            webhook_url = self.config['slack']['webhook_url']
            async with aiohttp.ClientSession() as session:
                test_payload = {"text": "🧪 Connectivity test"}
                async with session.post(webhook_url, json=test_payload, timeout=5) as response:
                    if response.status == 200:
                        test_results['slack'] = {'status': 'success'}
                    else:
                        test_results['slack'] = {'status': 'failed', 'error': f'HTTP {response.status}'}
        except Exception as e:
            test_results['slack'] = {'status': 'failed', 'error': str(e)}
    
    return test_results

def cleanup_old_logs(self, days_to_keep=30):
    """Clean up old notification logs"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        cutoff_timestamp = int(time.time()) - (days_to_keep * 24 * 3600)
        
        cursor.execute('DELETE FROM notification_log WHERE sent_at < ?', (cutoff_timestamp,))
        deleted_count = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'cleanup_logs', 
                                            f'Cleaned up {deleted_count} old notification logs')
        
        return deleted_count
        
    except Exception as e:
        self.logger.error(f"Error cleaning up notification logs: {e}")
        return 0

def export_notification_data(self, start_date=None, end_date=None, format='json'):
    """Export notification data for analysis"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        query = 'SELECT * FROM notification_log'
        params = []
        
        if start_date or end_date:
            conditions = []
            if start_date:
                conditions.append('sent_at >= ?')
                params.append(int(start_date.timestamp()))
            if end_date:
                conditions.append('sent_at <= ?')
                params.append(int(end_date.timestamp()))
            
            query += ' WHERE ' + ' AND '.join(conditions)
        
        query += ' ORDER BY sent_at DESC'
        
        cursor.execute(query, params)
        data = cursor.fetchall()
        
        # Get column names
        column_names = [description[0] for description in cursor.description]
        
        conn.close()
        
        if format.lower() == 'json':
            export_data = []
            for row in data:
                row_dict = dict(zip(column_names, row))
                # Convert timestamp to readable format
                if row_dict['sent_at']:
                    row_dict['sent_at_readable'] = datetime.fromtimestamp(row_dict['sent_at']).isoformat()
                export_data.append(row_dict)
            
            filename = f"notifications_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump({
                    'export_timestamp': datetime.now().isoformat(),
                    'total_records': len(export_data),
                    'data': export_data
                }, f, indent=2, default=str)
            
        elif format.lower() == 'csv':
            import csv
            filename = f"notifications_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                # Add readable timestamp column
                header = column_names + ['sent_at_readable']
                writer.writerow(header)
                
                for row in data:
                    row_list = list(row)
                    if row_list[7]:  # sent_at index
                        readable_time = datetime.fromtimestamp(row_list[7]).isoformat()
                    else:
                        readable_time = ''
                    row_list.append(readable_time)
                    writer.writerow(row_list)
        
        self.logger.info(f"Exported {len(data)} notification records to {filename}")
        return filename
        
    except Exception as e:
        self.logger.error(f"Error exporting notification data: {e}")
        return None

def create_custom_template(self, template_name, template_config):
    """Create custom notification template"""
    try:
        # Validate template config
        required_fields = ['title', 'emoji', 'color', 'priority']
        for field in required_fields:
            if field not in template_config:
                raise ValueError(f"Missing required field: {field}")
        
        # Add to templates
        self.templates[template_name] = template_config
        
        # Save to database
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO notification_templates 
            (template_name, template_data, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (
            template_name,
            json.dumps(template_config),
            int(time.time()),
            int(time.time())
        ))
        
        conn.commit()
        conn.close()
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'template_created', 
                                            f'Created custom template: {template_name}')
        
        return True
        
    except Exception as e:
        self.logger.error(f"Error creating custom template: {e}")
        return False

def load_custom_templates(self):
    """Load custom templates from database"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT template_name, template_data FROM notification_templates')
        templates = cursor.fetchall()
        
        conn.close()
        
        for template_name, template_data in templates:
            try:
                template_config = json.loads(template_data)
                self.templates[template_name] = template_config
            except json.JSONDecodeError as e:
                self.logger.error(f"Error parsing template {template_name}: {e}")
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'templates_loaded', 
                                            f'Loaded {len(templates)} custom templates')
        
    except Exception as e:
        self.logger.error(f"Error loading custom templates: {e}")

async def send_bulk_notification(self, notifications_data, batch_size=10):
    """Send multiple notifications in batches"""
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'bulk_send_start', 
                                        f'Sending {len(notifications_data)} bulk notifications')
    
    results = []
    
    # Process in batches to avoid overwhelming the queue
    for i in range(0, len(notifications_data), batch_size):
        batch = notifications_data[i:i + batch_size]
        batch_tasks = []
        
        for notif_data in batch:
            task = self.send_notification(
                notif_data.get('type', 'system_status'),
                notif_data.get('title', 'Bulk Notification'),
                notif_data.get('message', ''),
                notif_data.get('data', {}),
                notif_data.get('priority', 'medium')
            )
            batch_tasks.append(task)
        
        # Wait for batch to complete
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        results.extend(batch_results)
        
        # Small delay between batches
        if i + batch_size < len(notifications_data):
            await asyncio.sleep(1)
    
    successful = len([r for r in results if not isinstance(r, Exception)])
    failed = len(results) - successful
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'bulk_send_complete', 
                                        f'Bulk send complete - Success: {successful}, Failed: {failed}')
    
    return {'successful': successful, 'failed': failed, 'details': results}

def get_notification_preferences(self, user_id=None):
    """Get notification preferences for user or global"""
    # This could be extended to support per-user preferences
    return {
        'enabled_platforms': [platform for platform in ['telegram', 'discord', 'email', 'slack'] 
                                if self.config.get(platform, {}).get('enabled', False)],
        'notification_types': {
            platform: self.config.get(platform, {}).get('notification_types', {})
            for platform in ['telegram', 'discord', 'email', 'slack']
        },
        'priority_filter': self.config.get('priority_filter', 'low'),
        'rate_limits': self.rate_limits
    }

def update_notification_preferences(self, preferences):
    """Update notification preferences"""
    try:
        # Update configuration
        for platform, settings in preferences.items():
            if platform in self.config:
                self.config[platform].update(settings)
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'preferences_updated', 
                                            'Notification preferences updated')
        
        return True
        
    except Exception as e:
        self.logger.error(f"Error updating notification preferences: {e}")
        return False

async def pause_notifications(self, duration_minutes=0):
    """Pause notifications for specified duration (0 = indefinite)"""
    self.is_processing = False
    
    if duration_minutes > 0:
        # Resume after specified duration
        await asyncio.sleep(duration_minutes * 60)
        self.is_processing = True
        self._start_queue_processor()
    
    if self.advanced_logger:
        status = f"for {duration_minutes} minutes" if duration_minutes > 0 else "indefinitely"
        self.advanced_logger.debug_step('notifications', 'notifications_paused', 
                                        f'Notifications paused {status}')

async def resume_notifications(self):
    """Resume paused notifications"""
    if not self.is_processing:
        self.is_processing = True
        self._start_queue_processor()
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'notifications_resumed', 
                                            'Notifications resumed')

def get_queue_status(self):
    """Get detailed queue status"""
    return {
        'queue_size': self.notification_queue.qsize(),
        'is_processing': self.is_processing,
        'rate_limits': self.rate_limits,
        'delivery_stats': self.delivery_stats
    }

async def flush_queue(self):
    """Process all remaining notifications in queue immediately"""
    if self.advanced_logger:
        queue_size = self.notification_queue.qsize()
        self.advanced_logger.debug_step('notifications', 'queue_flush_start', 
                                        f'Flushing {queue_size} notifications from queue')
    
    processed = 0
    while not self.notification_queue.empty():
        try:
            notification = await asyncio.wait_for(
                self.notification_queue.get(), 
                timeout=1.0
            )
            await self._process_single_notification(notification)
            self.notification_queue.task_done()
            processed += 1
        except asyncio.TimeoutError:
            break
        except Exception as e:
            self.logger.error(f"Error flushing queue: {e}")
            break
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'queue_flush_complete', 
                                        f'Processed {processed} notifications during flush')
    
    return processed

async def shutdown(self):
    """Gracefully shutdown notification manager"""
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'shutdown_start', 
                                        'Starting notification manager shutdown')
    
    # Stop processing new notifications
    self.is_processing = False
    
    # Flush remaining notifications
    await self.flush_queue()
    
    # Close database connections (if any are persistent)
    # Clean up resources
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'shutdown_complete', 
                                        'Notification manager shutdown complete')

# Utility functions for easy integration

def create_notification_manager(config):
"""Factory function to create notification manager"""
return NotificationManager(config)

async def send_quick_alert(alert_type, message, config=None):
"""Quick alert function for simple integrations"""
if config is None:
    # Minimal configuration for testing
    config = {
        'notifications': {
            'telegram': {'enabled': False},
            'discord': {'enabled': False},
            'email': {'enabled': False},
            'slack': {'enabled': False},
            'webhook': {'enabled': False},
            'push': {'enabled': False}
        }
    }

manager = NotificationManager(config)
return await manager.send_notification(alert_type, f"Quick Alert: {alert_type}", message)

def get_default_config():
"""Get default notification configuration template"""
return {
    'notifications': {
        'max_retries': 3,
        'priority_filter': 'low',
        'telegram': {
            'enabled': False,
            'bot_token': '',
            'chat_ids': [],
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': True,
                'system_status': False,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'discord': {
            'enabled': False,
            'webhook_url': '',
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': True,
                'system_status': False,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'email': {
            'enabled': False,
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'username': '',
            'password': '',
            'recipients': [],
            'notification_types': {
                'rug_alert': True,
                'pump_alert': False,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': False,
                'system_status': True,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'slack': {
            'enabled': False,
            'webhook_url': '',
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': True,
                'system_status': True,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'webhook': {
            'enabled': False,
            'urls': [],
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': True,
                'trade_notification': True,
                'system_status': True,
                'error_alert': True,
                'performance_alert': True
            }
        },
        'push': {
            'enabled': False,
            'service': 'pushbullet',  # or 'ntfy'
            'api_key': '',  # for pushbullet
            'topic': '',    # for ntfy
            'server': '',   # for custom ntfy server
            'notification_types': {
                'rug_alert': True,
                'pump_alert': True,
                'fake_volume_alert': True,
                'bundle_alert': True,
                'rugcheck_failed': False,
                'trade_notification': False,
                'system_status': False,
                'error_alert': True,
                'performance_alert': False
            }
        }
    }
}"""
Multi-Platform Notification System
File: notifications.py

Comprehensive notification manager supporting:
- Telegram (with rich formatting and buttons)
- Discord (with embeds and webhooks)
- Email (with HTML templates)
- Slack (with blocks and attachments)
- Push notifications
- Custom webhooks
"""

import asyncio
import logging
import smtplib
import json
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import sqlite3
import time
import aiohttp
from typing import Dict, List, Optional, Union
import hashlib
from dataclasses import dataclass
from enum import Enum

try:
import telegram
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
TELEGRAM_AVAILABLE = True
except ImportError:
TELEGRAM_AVAILABLE = False
print("⚠️  python-telegram-bot not installed. Telegram notifications disabled.")

class NotificationPriority(Enum):
LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"

class NotificationStatus(Enum):
PENDING = "pending"
SENT = "sent"
FAILED = "failed"
RETRYING = "retrying"

@dataclass
class NotificationItem:
"""Data class for notification queue items"""
id: str
notification_type: str
title: str
message: str
data: Dict
template: Dict
priority: NotificationPriority
platforms: List[str]
retry_count: int = 0
max_retries: int = 3
created_at: float = None

def __post_init__(self):
    if self.created_at is None:
        self.created_at = time.time()

class NotificationManager:
"""
Advanced multi-platform notification system

Features:
- 📱 Telegram with rich formatting, buttons, and inline keyboards
- 🎮 Discord with colorful embeds and webhook integration  
- 📧 Email with HTML templates and attachments
- 💬 Slack with blocks and rich formatting
- 🔔 Push notifications via various services
- 📊 Notification analytics and delivery tracking
- 🔄 Retry logic with exponential backoff
- 🎯 Smart notification routing and filtering
"""

def __init__(self, config):
    self.config = config['notifications']
    self.logger = logging.getLogger(__name__)
    self.advanced_logger = None
    
    # Initialize notification channels
    self.telegram_bot = None
    self.notification_queue = asyncio.Queue()
    self.is_processing = False
    self.delivery_stats = {
        'telegram': {'sent': 0, 'failed': 0, 'retries': 0},
        'discord': {'sent': 0, 'failed': 0, 'retries': 0},
        'email': {'sent': 0, 'failed': 0, 'retries': 0},
        'slack': {'sent': 0, 'failed': 0, 'retries': 0},
        'webhook': {'sent': 0, 'failed': 0, 'retries': 0},
        'push': {'sent': 0, 'failed': 0, 'retries': 0}
    }
    
    # Rate limiting
    self.rate_limits = {
        'telegram': {'max_per_minute': 30, 'current': 0, 'last_reset': time.time()},
        'discord': {'max_per_minute': 30, 'current': 0, 'last_reset': time.time()},
        'email': {'max_per_minute': 10, 'current': 0, 'last_reset': time.time()},
        'slack': {'max_per_minute': 20, 'current': 0, 'last_reset': time.time()}
    }
    
    # Initialize components
    self._initialize_telegram()
    self._initialize_templates()
    self._setup_database()
    self._start_queue_processor()
    
    self.logger.info("🔔 Notification Manager initialized")
    
def set_advanced_logger(self, advanced_logger):
    """Set advanced logger instance"""
    self.advanced_logger = advanced_logger
    
def _initialize_telegram(self):
    """Initialize Telegram bot if enabled and available"""
    if not TELEGRAM_AVAILABLE:
        self.logger.warning("📱 Telegram bot library not available")
        return
        
    telegram_config = self.config.get('telegram', {})
    if telegram_config.get('enabled') and telegram_config.get('bot_token'):
        try:
            self.telegram_bot = Bot(token=telegram_config['bot_token'])
            self.logger.info("📱 Telegram bot initialized successfully")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('notifications', 'telegram_init_success', 
                                                'Telegram bot initialized')
        except Exception as e:
            self.logger.error(f"📱 Failed to initialize Telegram bot: {e}")
            if self.advanced_logger:
                self.advanced_logger.debug_step('notifications', 'telegram_init_failed', 
                                                f'Telegram init failed: {e}')
            
def _initialize_templates(self):
    """Initialize notification templates"""
    self.templates = {
        'rug_alert': {
            'title': '🚨 RUG PULL ALERT',
            'color': 0xFF0000,  # Red
            'emoji': '🚨',
            'priority': NotificationPriority.CRITICAL
        },
        'pump_alert': {
            'title': '🚀 PUMP DETECTED', 
            'color': 0x00FF00,  # Green
            'emoji': '🚀',
            'priority': NotificationPriority.HIGH
        },
        'fake_volume_alert': {
            'title': '📊 FAKE VOLUME DETECTED',
            'color': 0xFF8C00,  # Orange
            'emoji': '📊',
            'priority': NotificationPriority.HIGH
        },
        'bundle_alert': {
            'title': '📦 BUNDLE LAUNCH DETECTED',
            'color': 0xFF4500,  # Red-Orange
            'emoji': '📦',
            'priority': NotificationPriority.HIGH
        },
        'rugcheck_failed': {
            'title': '⚠️ RUGCHECK VERIFICATION FAILED',
            'color': 0xFFFF00,  # Yellow
            'emoji': '⚠️',
            'priority': NotificationPriority.MEDIUM
        },
        'trade_notification': {
            'title': '💰 TRADE EXECUTED',
            'color': 0x00BFFF,  # Deep Sky Blue
            'emoji': '💰',
            'priority': NotificationPriority.MEDIUM
        },
        'system_status': {
            'title': '🤖 SYSTEM UPDATE',
            'color': 0x808080,  # Gray
            'emoji': '🤖',
            'priority': NotificationPriority.LOW
        },
        'error_alert': {
            'title': '💥 SYSTEM ERROR',
            'color': 0xDC143C,  # Crimson
            'emoji': '💥',
            'priority': NotificationPriority.CRITICAL
        },
        'performance_alert': {
            'title': '⚡ PERFORMANCE ALERT',
            'color': 0xFFA500,  # Orange
            'emoji': '⚡',
            'priority': NotificationPriority.MEDIUM
        }
    }
    
def _setup_database(self):
    """Setup notification tracking database"""
    try:
        conn = sqlite3.connect('notifications.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id TEXT UNIQUE,
                notification_type TEXT,
                platform TEXT,
                recipient TEXT,
                title TEXT,
                message TEXT,
                status TEXT,
                sent_at INTEGER,
                delivery_time REAL,
                retry_count INTEGER DEFAULT 0,
                error_message TEXT,
                priority TEXT,
                data_hash TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                platform TEXT,
                notification_type TEXT,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                avg_delivery_time REAL DEFAULT 0,
                retry_count INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_name TEXT UNIQUE,
                template_data TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notification_log_date ON notification_log(sent_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notification_log_platform ON notification_log(platform)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_notification_log_type ON notification_log(notification_type)')
        
        conn.commit()
        conn.close()
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'database_setup', 
                                            'Notification database initialized')
            
    except Exception as e:
        self.logger.error(f"Error setting up notification database: {e}")

def _start_queue_processor(self):
    """Start the notification queue processor"""
    if not self.is_processing:
        self.is_processing = True
        asyncio.create_task(self._process_notification_queue())
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'queue_processor_started', 
                                            'Notification queue processor started')

async def _process_notification_queue(self):
    """Process notifications from the queue with rate limiting and retries"""
    while self.is_processing:
        try:
            # Wait for notification with timeout
            try:
                notification = await asyncio.wait_for(
                    self.notification_queue.get(), 
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            
            # Check rate limits before processing
            await self._enforce_rate_limits(notification.platforms)
            
            # Process the notification
            await self._process_single_notification(notification)
            
            # Mark task as done
            self.notification_queue.task_done()
            
        except Exception as e:
            self.logger.error(f"Error in notification queue processor: {e}")
            if self.advanced_logger:
                self.advanced_logger.debug_step('notifications', 'queue_processor_error', 
                                                f'Queue processor error: {e}')
            await asyncio.sleep(1)

async def _enforce_rate_limits(self, platforms):
    """Enforce rate limits for platforms"""
    current_time = time.time()
    
    for platform in platforms:
        if platform not in self.rate_limits:
            continue
            
        rate_limit = self.rate_limits[platform]
        
        # Reset counter if a minute has passed
        if current_time - rate_limit['last_reset'] >= 60:
            rate_limit['current'] = 0
            rate_limit['last_reset'] = current_time
        
        # Wait if rate limit exceeded
        if rate_limit['current'] >= rate_limit['max_per_minute']:
            wait_time = 60 - (current_time - rate_limit['last_reset'])
            if wait_time > 0:
                if self.advanced_logger:
                    self.advanced_logger.debug_step('notifications', 'rate_limit_wait', 
                                                    f'Rate limit hit for {platform}, waiting {wait_time:.1f}s')
                await asyncio.sleep(wait_time)
                
                # Reset after waiting
                rate_limit['current'] = 0
                rate_limit['last_reset'] = time.time()

async def _process_single_notification(self, notification: NotificationItem):
    """Process a single notification with retry logic"""
    notification_id = notification.id
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'processing_notification', 
                                        f'Processing notification {notification_id}: {notification.title}')
    
    # Send to enabled platforms
    tasks = []
    
    for platform in notification.platforms:
        if platform == 'telegram' and self._should_notify('telegram', notification.notification_type):
            tasks.append(self._send_telegram_notification_safe(notification))
        elif platform == 'discord' and self._should_notify('discord', notification.notification_type):
            tasks.append(self._send_discord_notification_safe(notification))
        elif platform == 'email' and self._should_notify('email', notification.notification_type):
            tasks.append(self._send_email_notification_safe(notification))
        elif platform == 'slack' and self._should_notify('slack', notification.notification_type):
            tasks.append(self._send_slack_notification_safe(notification))
        elif platform == 'webhook':
            tasks.append(self._send_webhook_notification_safe(notification))
        elif platform == 'push':
            tasks.append(self._send_push_notification_safe(notification))
    
    # Execute all notifications concurrently
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check results and handle retries
        failed_platforms = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_platforms.append(notification.platforms[i])
                if self.advanced_logger:
                    self.advanced_logger.debug_step('notifications', 'platform_failed', 
                                                    f'Platform {notification.platforms[i]} failed: {result}')
        
        # Retry failed platforms if under retry limit
        if failed_platforms and notification.retry_count < notification.max_retries:
            notification.retry_count += 1
            notification.platforms = failed_platforms
            
            # Exponential backoff
            retry_delay = min(60, 2 ** notification.retry_count)
            await asyncio.sleep(retry_delay)
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('notifications', 'retrying_notification', 
                                                f'Retrying notification {notification_id}, attempt {notification.retry_count}')
            
            # Re-add to queue for retry
            await self.notification_queue.put(notification)

async def send_notification(self, notification_type, title, message, data=None, priority='medium'):
    """
    Main notification sending function
    
    Routes notifications to all enabled platforms based on configuration
    """
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'send_notification_start', 
                                        f'🔔 Sending {notification_type} notification: {title}')
    
    # Get template configuration
    template = self.templates.get(notification_type, self.templates['system_status'])
    
    # Generate unique notification ID
    notification_id = self._generate_notification_id(notification_type, title, message)
    
    # Determine target platforms
    target_platforms = self._get_target_platforms(notification_type)
    
    if not target_platforms:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'no_platforms_enabled', 
                                            f'No platforms enabled for {notification_type}')
        return {'success': 0, 'failed': 0, 'notification_id': notification_id}
    
    # Create notification item
    notification_item = NotificationItem(
        id=notification_id,
        notification_type=notification_type,
        title=title,
        message=message,
        data=data or {},
        template=template,
        priority=NotificationPriority(priority) if isinstance(priority, str) else priority,
        platforms=target_platforms,
        max_retries=self.config.get('max_retries', 3)
    )
    
    # Add to queue
    await self.notification_queue.put(notification_item)
    
    if self.advanced_logger:
        self.advanced_logger.debug_step('notifications', 'notification_queued', 
                                        f'Notification {notification_id} queued for {len(target_platforms)} platforms')
    
    return {
        'success': 0,  # Will be updated by queue processor
        'failed': 0,
        'notification_id': notification_id,
        'queued_platforms': target_platforms
    }

def _generate_notification_id(self, notification_type, title, message):
    """Generate unique notification ID"""
    content = f"{notification_type}:{title}:{message}:{time.time()}"
    return hashlib.md5(content.encode()).hexdigest()[:12]

def _get_target_platforms(self, notification_type):
    """Get list of platforms that should receive this notification type"""
    target_platforms = []
    
    for platform in ['telegram', 'discord', 'email', 'slack', 'webhook', 'push']:
        if self._should_notify(platform, notification_type):
            target_platforms.append(platform)
    
    return target_platforms

def _should_notify(self, platform, notification_type):
    """Check if notification should be sent to specific platform"""
    platform_config = self.config.get(platform, {})
    
    if not platform_config.get('enabled', False):
        return False
        
    notification_types = platform_config.get('notification_types', {})
    return notification_types.get(notification_type, False)

async def _send_telegram_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for Telegram notifications with error handling"""
    try:
        await self._send_telegram_notification(notification)
        self.rate_limits['telegram']['current'] += 1
        self.delivery_stats['telegram']['sent'] += 1
    except Exception as e:
        self.delivery_stats['telegram']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['telegram']['retries'] += 1
        raise e

async def _send_telegram_notification(self, notification: NotificationItem):
    """
    Send rich Telegram notification with formatting and buttons
    """
    if not self.telegram_bot:
        raise Exception("Telegram bot not initialized")
        
    start_time = time.time()
    
    try:
        template = notification.template
        title = notification.title
        message = notification.message
        data = notification.data
        
        # Format message with Telegram markdown
        formatted_message = f"*{template['emoji']} {title}*\n\n{message}"
        
        # Add data fields if present
        if data:
            formatted_message += "\n\n📊 *Details:*"
            for key, value in data.items():
                if key in ['timestamp', 'analysis_timestamp']:
                    continue  # Skip internal timestamps
                    
                if isinstance(value, (int, float)):
                    if 'usd' in key.lower() or 'price' in key.lower():
                        formatted_message += f"\n• *{self._format_field_name(key)}:* ${value:,.2f}"
                    elif 'confidence' in key.lower() or 'score' in key.lower():
                        formatted_message += f"\n• *{self._format_field_name(key)}:* {value:.1%}"
                    else:
                        formatted_message += f"\n• *{self._format_field_name(key)}:* {value:,}"
                else:
                    formatted_message += f"\n• *{self._format_field_name(key)}:* {value}"
        
        # Add timestamp
        formatted_message += f"\n\n🕐 {datetime.now().strftime('%H:%M:%S UTC')}"
        
        # Create inline keyboard for interactive buttons
        keyboard = self._create_telegram_keyboard(notification)
        
        # Send to all configured chat IDs
        telegram_config = self.config['telegram']
        for chat_id in telegram_config['chat_ids']:
            try:
                await self.telegram_bot.send_message(
                    chat_id=chat_id,
                    text=formatted_message,
                    parse_mode='Markdown',
                    disable_web_page_preview=True,
                    reply_markup=keyboard
                )
                
                delivery_time = time.time() - start_time
                
                # Log successful delivery
                self._log_notification_delivery(
                    notification.id, notification.notification_type, 'telegram', chat_id,
                    title, message, 'sent', delivery_time, notification.retry_count
                )
                
                if self.advanced_logger:
                    self.advanced_logger.log_notification_sent('notifications', 
                                                                notification.notification_type, 
                                                                'telegram', True,
                                                                f'Delivered in {delivery_time:.3f}s')
                
            except Exception as e:
                self.logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
                self._log_notification_delivery(
                    notification.id, notification.notification_type, 'telegram', chat_id,
                    title, message, 'failed', 0, notification.retry_count, str(e)
                )
                raise e
                
    except Exception as e:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'telegram_send_error', 
                                            f'❌ Telegram notification failed: {e}')
        raise

def _create_telegram_keyboard(self, notification: NotificationItem):
    """Create interactive keyboard for Telegram notifications"""
    if not TELEGRAM_AVAILABLE:
        return None
        
    notification_type = notification.notification_type
    data = notification.data
    
    keyboard = []
    
    # Add relevant action buttons based on notification type
    if notification_type in ['rug_alert', 'fake_volume_alert', 'bundle_alert']:
        keyboard.append([
            InlineKeyboardButton("🚫 Add to Blacklist", callback_data=f"blacklist_{data.get('token_address', '')}")
        ])
        
    if notification_type == 'pump_alert':
        keyboard.append([
            InlineKeyboardButton("💰 Check Trading", callback_data=f"trade_check_{data.get('token_address', '')}")
        ])
        
    # Always add info button
    if data.get('token_address'):
        keyboard.append([
            InlineKeyboardButton("📊 View on DexScreener", 
                                url=f"https://dexscreener.com/solana/{data['token_address']}")
        ])
        
    # Add notification management buttons
    keyboard.append([
        InlineKeyboardButton("🔕 Mute Type", callback_data=f"mute_{notification_type}"),
        InlineKeyboardButton("📊 Stats", callback_data="show_stats")
    ])
        
    if keyboard:
        return InlineKeyboardMarkup(keyboard)
    return None

async def _send_discord_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for Discord notifications"""
    try:
        await self._send_discord_notification(notification)
        self.rate_limits['discord']['current'] += 1
        self.delivery_stats['discord']['sent'] += 1
    except Exception as e:
        self.delivery_stats['discord']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['discord']['retries'] += 1
        raise e

async def _send_discord_notification(self, notification: NotificationItem):
    """
    Send rich Discord webhook notification with embeds
    """
    discord_config = self.config.get('discord', {})
    webhook_url = discord_config.get('webhook_url')
    
    if not webhook_url:
        raise Exception("Discord webhook URL not configured")
        
    start_time = time.time()
    
    try:
        template = notification.template
        title = notification.title
        message = notification.message
        data = notification.data
        
        # Create rich embed
        embed = {
            "title": f"{template['emoji']} {title}",
            "description": message,
            "color": template['color'],
            "timestamp": datetime.now().isoformat(),
            "footer": {
                "text": "DexScreener Solana Bot",
                "icon_url": "https://dexscreener.com/favicon.ico"
            },
            "fields": []
        }
        
        # Add priority indicator
        priority_emojis = {
            NotificationPriority.LOW: "🟢",
            NotificationPriority.MEDIUM: "🟡", 
            NotificationPriority.HIGH: "🟠",
            NotificationPriority.CRITICAL: "🔴"
        }
        
        embed["fields"].append({
            "name": "Priority",
            "value": f"{priority_emojis.get(notification.priority, '⚪')} {notification.priority.value.title()}",
            "inline": True
        })
        
        # Add data fields
        if data:
            for key, value in data.items():
                if key in ['timestamp', 'analysis_timestamp']:
                    continue
                    
                field_value = str(value)
                if isinstance(value, (int, float)):
                    if 'usd' in key.lower() or 'price' in key.lower():
                        field_value = f"${value:,.2f}"
                    elif 'confidence' in key.lower() or 'score' in key.lower():
                        field_value = f"{value:.1%}"
                    else:
                        field_value = f"{value:,}"
                
                embed["fields"].append({
                    "name": self._format_field_name(key),
                    "value": field_value,
                    "inline": True
                })
        
        # Add DexScreener link if token address available
        if data.get('token_address'):
            embed["url"] = f"https://dexscreener.com/solana/{data['token_address']}"
        
        # Add retry info if this is a retry
        if notification.retry_count > 0:
            embed["fields"].append({
                "name": "Retry Info",
                "value": f"Attempt {notification.retry_count + 1}/{notification.max_retries + 1}",
                "inline": True
            })
        
        payload = {"embeds": [embed]}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10) as response:
                response.raise_for_status()
        
        delivery_time = time.time() - start_time
        
        # Log successful delivery
        self._log_notification_delivery(
            notification.id, notification.notification_type, 'discord', 'webhook',
            title, message, 'sent', delivery_time, notification.retry_count
        )
        
        if self.advanced_logger:
            self.advanced_logger.log_notification_sent('notifications', 
                                                        notification.notification_type, 
                                                        'discord', True,
                                                        f'Delivered in {delivery_time:.3f}s')
        
    except Exception as e:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'discord_send_error', 
                                            f'❌ Discord notification failed: {e}')
        raise

async def _send_email_notification_safe(self, notification: NotificationItem):
    """Safe wrapper for Email notifications"""
    try:
        await self._send_email_notification(notification)
        self.rate_limits['email']['current'] += 1
        self.delivery_stats['email']['sent'] += 1
    except Exception as e:
        self.delivery_stats['email']['failed'] += 1
        if notification.retry_count > 0:
            self.delivery_stats['email']['retries'] += 1
        raise e

async def _send_email_notification(self, notification: NotificationItem):
    """
    Send HTML email notification with rich formatting
    """
    email_config = self.config.get('email', {})
    
    if not all([email_config.get('username'), email_config.get('password'), 
                email_config.get('recipients')]):
        raise Exception("Email configuration incomplete")
        
    start_time = time.time()
    
    try:
        template = notification.template
        title = notification.title
        message = notification.message
        data = notification.data
        
        # Create HTML email
        html_content = self._create_html_email(notification)
        
        msg = MIMEMultipart('alternative')
        msg['From'] = email_config['username']
        msg['Subject'] = f"[DexScreener Bot] {template['emoji']} {title}"
        
        # Add priority headers
        if notification.priority == NotificationPriority.CRITICAL:
            msg['X-Priority'] = '1'
            msg['X-MSMail-Priority'] = 'High'
            msg['Importance'] = 'High'
        
        # Add HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        # Send to all recipients
        server = smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port'])
        server.starttls()
        server.login(email_config['username'], email_config['password'])
        
        for recipient in email_config['recipients']:
            msg['To'] = recipient
            server.send_message(msg)
            
            delivery_time = time.time() - start_time
            
            self._log_notification_delivery(
                notification.id, notification.notification_type, 'email', recipient,
                title, message, 'sent', delivery_time, notification.retry_count
            )
        
        server.quit()
        
        if self.advanced_logger:
            self.advanced_logger.log_notification_sent('notifications', 
                                                        notification.notification_type, 
                                                        'email', True,
                                                        f'Sent to {len(email_config["recipients"])} recipients')
        
    except Exception as e:
        if self.advanced_logger:
            self.advanced_logger.debug_step('notifications', 'email_send_error', 
                                            f'❌ Email notification failed: {e}')
        raise