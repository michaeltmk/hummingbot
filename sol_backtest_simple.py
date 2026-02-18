#!/usr/bin/env python3
"""
SOL MACD BB Strategy Backtest - Simplified Version
Using actual candle data from binance_SOL-USDT_20250910_20250914.csv
"""

import pandas as pd
import numpy as np
from datetime import datetime

def load_candle_data(filepath):
    """Load and prepare candle data"""
    df = pd.read_csv(filepath)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('timestamp', inplace=True)
    return df

def calculate_sma(series, period):
    """Calculate Simple Moving Average"""
    return series.rolling(window=period).mean()

def calculate_bollinger_bands(df, period=20, std_dev=2):
    """Calculate Bollinger Bands"""
    sma = calculate_sma(df['close'], period)
    std = df['close'].rolling(window=period).std()
    
    df['bb_upper'] = sma + (std * std_dev)
    df['bb_middle'] = sma
    df['bb_lower'] = sma - (std * std_dev)
    df['bbp'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    
    return df

def calculate_ema(series, period):
    """Calculate Exponential Moving Average"""
    return series.ewm(span=period).mean()

def calculate_macd(df, fast=12, slow=26, signal=9):
    """Calculate MACD"""
    ema_fast = calculate_ema(df['close'], fast)
    ema_slow = calculate_ema(df['close'], slow)
    
    df['macd'] = ema_fast - ema_slow
    df['macd_signal'] = calculate_ema(df['macd'], signal)
    df['macd_histogram'] = df['macd'] - df['macd_signal']
    
    return df

def add_indicators(df, config):
    """Add MACD and Bollinger Bands indicators"""
    # Bollinger Bands
    df = calculate_bollinger_bands(df, config['bb_length'], config['bb_std'])
    
    # MACD
    df = calculate_macd(df, config['macd_fast'], config['macd_slow'], config['macd_signal'])
    
    return df

def generate_signals(df, config):
    """Generate trading signals based on strategy logic"""
    # Long condition: BBP < threshold AND MACDH > 0 AND MACD < 0
    long_condition = (
        (df['bbp'] < config['bb_long_threshold']) & 
        (df['macd_histogram'] > 0) & 
        (df['macd'] < 0)
    )
    
    # Short condition: BBP > threshold AND MACDH < 0 AND MACD > 0  
    short_condition = (
        (df['bbp'] > config['bb_short_threshold']) & 
        (df['macd_histogram'] < 0) & 
        (df['macd'] > 0)
    )
    
    df['signal'] = 0
    df.loc[long_condition, 'signal'] = 1
    df.loc[short_condition, 'signal'] = -1
    
    return df

def simulate_trades(df, config):
    """Simulate trading with position management"""
    positions = []
    current_positions = []
    
    for i, row in df.iterrows():
        if pd.isna(row['signal']) or pd.isna(row['close']):
            continue
            
        price = row['close']
        signal = row['signal']
        
        # Close existing positions
        positions_to_close = []
        for pos in current_positions:
            if pos['side'] == 'LONG':
                # Check exit conditions
                pnl_pct = (price - pos['entry_price']) / pos['entry_price']
                
                if pnl_pct >= config['take_profit']:
                    # Take profit
                    pos['exit_price'] = price
                    pos['exit_time'] = i
                    pos['exit_type'] = 'TAKE_PROFIT'
                    pos['pnl'] = pos['size'] * pnl_pct
                    positions.append(pos)
                    positions_to_close.append(pos)
                    
                elif pnl_pct <= -config['stop_loss']:
                    # Stop loss
                    pos['exit_price'] = price
                    pos['exit_time'] = i
                    pos['exit_type'] = 'STOP_LOSS'
                    pos['pnl'] = pos['size'] * pnl_pct
                    positions.append(pos)
                    positions_to_close.append(pos)
                    
                elif pnl_pct >= config['trailing_activation']:
                    # Update trailing stop
                    trailing_stop_price = price * (1 - config['trailing_delta'])
                    if 'trailing_stop' not in pos or trailing_stop_price > pos['trailing_stop']:
                        pos['trailing_stop'] = trailing_stop_price
                        
                    # Check if trailing stop hit
                    if 'trailing_stop' in pos and price <= pos['trailing_stop']:
                        pos['exit_price'] = price
                        pos['exit_time'] = i
                        pos['exit_type'] = 'TRAILING_STOP'
                        pos['pnl'] = pos['size'] * pnl_pct
                        positions.append(pos)
                        positions_to_close.append(pos)
                        
            elif pos['side'] == 'SHORT':
                # Similar logic for shorts
                pnl_pct = (pos['entry_price'] - price) / pos['entry_price']
                
                if pnl_pct >= config['take_profit']:
                    pos['exit_price'] = price
                    pos['exit_time'] = i
                    pos['exit_type'] = 'TAKE_PROFIT'
                    pos['pnl'] = pos['size'] * pnl_pct
                    positions.append(pos)
                    positions_to_close.append(pos)
                    
                elif pnl_pct <= -config['stop_loss']:
                    pos['exit_price'] = price
                    pos['exit_time'] = i
                    pos['exit_type'] = 'STOP_LOSS'
                    pos['pnl'] = pos['size'] * pnl_pct
                    positions.append(pos)
                    positions_to_close.append(pos)
        
        # Remove closed positions
        for pos in positions_to_close:
            current_positions.remove(pos)
            
        # Open new positions on signal
        if signal != 0 and len(current_positions) < config['max_executors_per_side']:
            position_size = config['total_amount_quote'] / config['max_executors_per_side']
            
            position = {
                'entry_time': i,
                'entry_price': price,
                'side': 'LONG' if signal == 1 else 'SHORT',
                'size': position_size
            }
            current_positions.append(position)
    
    # Close any remaining positions at the end
    if current_positions:
        final_price = df['close'].iloc[-1]
        final_time = df.index[-1]
        for pos in current_positions:
            if pos['side'] == 'LONG':
                pnl_pct = (final_price - pos['entry_price']) / pos['entry_price']
            else:
                pnl_pct = (pos['entry_price'] - final_price) / pos['entry_price']
                
            pos['exit_price'] = final_price
            pos['exit_time'] = final_time
            pos['exit_type'] = 'TIME_LIMIT'
            pos['pnl'] = pos['size'] * pnl_pct
            positions.append(pos)
    
    return positions

def analyze_results(positions, config):
    """Analyze backtest results"""
    if not positions:
        print("No trades executed")
        return {}
        
    df_trades = pd.DataFrame(positions)
    
    # Calculate metrics
    total_trades = len(positions)
    winning_trades = len(df_trades[df_trades['pnl'] > 0])
    losing_trades = len(df_trades[df_trades['pnl'] < 0])
    
    total_pnl = df_trades['pnl'].sum()
    total_volume = df_trades['size'].sum()
    
    win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
    
    avg_win = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
    
    profit_factor = abs(avg_win * winning_trades / (avg_loss * losing_trades)) if avg_loss != 0 and losing_trades > 0 else float('inf')
    
    # Max drawdown calculation
    cumulative_pnl = df_trades['pnl'].cumsum()
    running_max = cumulative_pnl.expanding().max()
    drawdown = cumulative_pnl - running_max
    max_drawdown = drawdown.min()
    
    # Exit type analysis
    exit_types = df_trades['exit_type'].value_counts()
    
    # Side analysis
    long_trades = df_trades[df_trades['side'] == 'LONG']
    short_trades = df_trades[df_trades['side'] == 'SHORT']
    
    long_win_rate = len(long_trades[long_trades['pnl'] > 0]) / len(long_trades) * 100 if len(long_trades) > 0 else 0
    short_win_rate = len(short_trades[short_trades['pnl'] > 0]) / len(short_trades) * 100 if len(short_trades) > 0 else 0
    
    # Print results
    print("="*50)
    print("BACKTEST RESULTS")
    print("="*50)
    print(f"Net PNL (Quote): {total_pnl:.2f}")
    print(f"Net PNL (%): {(total_pnl/config['total_amount_quote']*100):.2f}%")
    print(f"Max Drawdown (USD): {max_drawdown:.2f}")
    print(f"Max Drawdown (%): {(max_drawdown/config['total_amount_quote']*100):.2f}%")
    print(f"Total Volume (Quote): {total_volume:.2f}")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Total Trades: {total_trades}")
    print("")
    print("ACCURACY METRICS")
    print("-"*30)
    print(f"Global Accuracy: {win_rate:.2f}%")
    print(f"Total Long: {len(long_trades)}")
    print(f"Total Short: {len(short_trades)}")
    print(f"Accuracy Long: {long_win_rate:.2f}%")
    print(f"Accuracy Short: {short_win_rate:.2f}%")
    print("")
    print("CLOSE TYPES")
    print("-"*30)
    for exit_type, count in exit_types.items():
        print(f"{exit_type}: {count}")
    
    return {
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'max_drawdown': max_drawdown,
        'total_trades': total_trades
    }

def main():
    # Load data
    print("Loading candle data...")
    df = load_candle_data('/home/michael/deploy-1/binance_SOL-USDT_20250910_20250914.csv')
    print(f"Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}")
    
    # Test configurations
    configs = {
        'v0.3_original': {
            'bb_length': 100,
            'bb_long_threshold': 0.1,
            'bb_short_threshold': 0.9,
            'bb_std': 2.0,
            'macd_fast': 21,
            'macd_slow': 42,
            'macd_signal': 9,
            'stop_loss': 0.02,
            'take_profit': 0.1,
            'trailing_activation': 0.02,
            'trailing_delta': 0.02,
            'max_executors_per_side': 10,
            'total_amount_quote': 1000
        },
        'v0.5_optimized': {
            'bb_length': 50,
            'bb_long_threshold': 0.25,
            'bb_short_threshold': 0.98,
            'bb_std': 2.0,
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
            'stop_loss': 0.02,
            'take_profit': 0.025,
            'trailing_activation': 0.012,
            'trailing_delta': 0.008,
            'max_executors_per_side': 4,
            'total_amount_quote': 1000
        }
    }
    
    for config_name, config in configs.items():
        print(f"\n{'='*60}")
        print(f"TESTING CONFIGURATION: {config_name}")
        print(f"{'='*60}")
        
        # Add indicators
        df_test = df.copy()
        df_test = add_indicators(df_test, config)
        
        # Generate signals  
        df_test = generate_signals(df_test, config)
        
        # Check for signals
        signal_count = df_test['signal'].value_counts()
        print(f"Signal distribution: {dict(signal_count)}")
        
        # Simulate trades
        positions = simulate_trades(df_test, config)
        
        # Analyze results
        results = analyze_results(positions, config)

if __name__ == "__main__":
    main()
