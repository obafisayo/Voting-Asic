`default_nettype none

/*
 * MOD-01 — UART Receiver (Wisdom)
 *
 * Standard 8N1 UART receiver that assembles a 20-bit voter ID from three
 * successive UART frames:
 *   Frame 0 → voter_id[7:0]
 *   Frame 1 → voter_id[15:8]
 *   Frame 2 → voter_id[19:16]  (lower nibble only; upper nibble ignored)
 *
 * After the third frame is validated, voter_id_out is updated and data_ready
 * pulses high for exactly one clock cycle.
 *
 * Parameters
 *   CLK_FREQ  — system clock frequency in Hz (default 50 MHz)
 *   BAUD_RATE — UART baud rate in bps       (default 115200)
 */

module mod01_uart_rx #(
    parameter CLK_FREQ  = 50_000_000,
    parameter BAUD_RATE = 115_200
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        rx,           // UART serial input (idle high)
    output reg  [19:0] voter_id_out,
    output reg         data_ready
);

    localparam integer BAUD_DIV  = CLK_FREQ / BAUD_RATE;
    localparam integer HALF_BAUD = BAUD_DIV / 2;

    // ── 2-FF synchroniser (metastability protection) ─────────────────────────
    reg rx_s1, rx_sync;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_s1   <= 1'b1;
            rx_sync <= 1'b1;
        end else begin
            rx_s1   <= rx;
            rx_sync <= rx_s1;
        end
    end

    // ── UART byte receiver ────────────────────────────────────────────────────
    localparam [1:0] IDLE = 2'd0, START = 2'd1, DATA = 2'd2, STOP = 2'd3;

    reg [1:0]  uart_state;
    reg [15:0] baud_cnt;
    reg [2:0]  bit_cnt;
    reg [7:0]  shift_reg;
    reg        byte_done;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            uart_state <= IDLE;
            baud_cnt   <= 16'd0;
            bit_cnt    <= 3'd0;
            shift_reg  <= 8'd0;
            byte_done  <= 1'b0;
        end else begin
            byte_done <= 1'b0;

            case (uart_state)
                IDLE: begin
                    if (!rx_sync) begin             // falling edge = start bit
                        uart_state <= START;
                        baud_cnt   <= HALF_BAUD[15:0]; // sample at mid-bit
                    end
                end

                START: begin
                    if (baud_cnt == 16'd0) begin
                        if (!rx_sync) begin         // confirmed start bit
                            uart_state <= DATA;
                            baud_cnt   <= BAUD_DIV[15:0];
                            bit_cnt    <= 3'd0;
                        end else begin
                            uart_state <= IDLE;     // noise — abort
                        end
                    end else begin
                        baud_cnt <= baud_cnt - 1;
                    end
                end

                DATA: begin
                    if (baud_cnt == 16'd0) begin
                        shift_reg <= {rx_sync, shift_reg[7:1]}; // LSB first
                        baud_cnt  <= BAUD_DIV[15:0];
                        if (bit_cnt == 3'd7)
                            uart_state <= STOP;
                        else
                            bit_cnt <= bit_cnt + 1;
                    end else begin
                        baud_cnt <= baud_cnt - 1;
                    end
                end

                STOP: begin
                    if (baud_cnt == 16'd0) begin
                        uart_state <= IDLE;
                        if (rx_sync)               // valid stop bit
                            byte_done <= 1'b1;
                        // on framing error simply discard the byte
                    end else begin
                        baud_cnt <= baud_cnt - 1;
                    end
                end

                default: uart_state <= IDLE;
            endcase
        end
    end

    // ── Frame assembler: 3 bytes → 20-bit voter ID ───────────────────────────
    reg [1:0] frame_cnt;
    reg [7:0] byte0, byte1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            frame_cnt    <= 2'd0;
            byte0        <= 8'd0;
            byte1        <= 8'd0;
            voter_id_out <= 20'd0;
            data_ready   <= 1'b0;
        end else begin
            data_ready <= 1'b0;

            if (byte_done) begin
                case (frame_cnt)
                    2'd0: begin
                        byte0     <= shift_reg;
                        frame_cnt <= 2'd1;
                    end
                    2'd1: begin
                        byte1     <= shift_reg;
                        frame_cnt <= 2'd2;
                    end
                    2'd2: begin
                        // Assemble: {voter_id[19:16], voter_id[15:8], voter_id[7:0]}
                        voter_id_out <= {shift_reg[3:0], byte1, byte0};
                        data_ready   <= 1'b1;
                        frame_cnt    <= 2'd0;
                    end
                    default: frame_cnt <= 2'd0;
                endcase
            end
        end
    end

endmodule
