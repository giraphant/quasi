// Closed-value and text primitives shared by surviving operation rows.

const CONTROL_CHARS = new RegExp("[\\u0000-\\u001f\\u007f-\\u009f]");

export const validText = (
  value: unknown,
  min: number,
  max: number,
): value is string =>
  typeof value === "string" &&
  value === value.trim() &&
  value.length >= min &&
  value.length <= max &&
  !CONTROL_CHARS.test(value);

export const exactKeys = (value: any, keys: readonly string[]): boolean =>
  !!(
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every((key) =>
      Object.prototype.hasOwnProperty.call(value, key),
    )
  );

export function sameClosedValue(left: any, right: any): boolean {
  if (Array.isArray(left) || Array.isArray(right))
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) =>
        sameClosedValue(value, right[index]),
      )
    );
  if (
    left &&
    right &&
    typeof left === "object" &&
    typeof right === "object"
  ) {
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    return (
      leftKeys.length === rightKeys.length &&
      leftKeys.every(
        (key) =>
          Object.prototype.hasOwnProperty.call(right, key) &&
          sameClosedValue(left[key], right[key]),
      )
    );
  }
  return Object.is(left, right);
}
