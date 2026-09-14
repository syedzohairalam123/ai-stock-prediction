import { InputHTMLAttributes, forwardRef } from 'react';

interface BaseInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label?: string;
  error?: string;
  helperText?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  variant?: 'default' | 'outlined' | 'filled';
  size?: 'sm' | 'md' | 'lg';
}

const BaseInput = forwardRef<HTMLInputElement, BaseInputProps>(
  (
    {
      label,
      error,
      helperText,
      leftIcon,
      rightIcon,
      variant = 'default',
      size = 'md',
      className = '',
      ...props
    },
    ref
  ) => {
    const baseClasses = 'base-input';
    const variantClasses = `base-input-${variant}`;
    const sizeClasses = `base-input-${size}`;
    const errorClass = error ? 'base-input-error' : '';
    const hasLeftIcon = leftIcon ? 'base-input-has-left-icon' : '';
    const hasRightIcon = rightIcon ? 'base-input-has-right-icon' : '';

    return (
      <div className="base-input-wrapper">
        {label && <label className="base-input-label">{label}</label>}
        <div className="base-input-container">
          {leftIcon && <span className="base-input-left-icon">{leftIcon}</span>}
          <input
            ref={ref}
            className={`${baseClasses} ${variantClasses} ${sizeClasses} ${errorClass} ${hasLeftIcon} ${hasRightIcon} ${className}`}
            {...props}
          />
          {rightIcon && <span className="base-input-right-icon">{rightIcon}</span>}
        </div>
        {error && <span className="base-input-error-text">{error}</span>}
        {helperText && !error && <span className="base-input-helper-text">{helperText}</span>}
      </div>
    );
  }
);

BaseInput.displayName = 'BaseInput';

export default BaseInput;